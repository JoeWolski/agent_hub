from __future__ import annotations

import asyncio
import codecs
import fcntl
import hashlib
import json
import os
import queue
import re
import signal
import struct
import subprocess
import shutil
import termios
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread, current_thread
from typing import Any

import click
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


STATE_FILE_NAME = "state.json"
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8765
TERMINAL_LOG_TAIL_BYTES = 200_000
TERMINAL_QUEUE_MAX = 256
DEFAULT_CODEX_IMAGE = "codex-ubuntu2204:latest"
DEFAULT_PTY_COLS = 160
DEFAULT_PTY_ROWS = 48
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


@dataclass
class ChatRuntime:
    process: subprocess.Popen
    master_fd: int
    listeners: set[queue.Queue[str | None]] = field(default_factory=set)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def _default_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "codex-hub"


def _default_config_file() -> Path:
    config_file = _repo_root() / "config" / "codex.config.toml"
    if config_file.exists():
        return config_file

    fallback = Path.cwd() / "config" / "codex.config.toml"
    if fallback.exists():
        return fallback

    return config_file


def _frontend_dist_dir() -> Path:
    return _repo_root() / "web" / "dist"


def _frontend_index_file() -> Path:
    return _frontend_dist_dir() / "index.html"


def _run_cli_command(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if result.returncode == 0:
        return
    message = ((result.stdout or "") + (result.stderr or "")).strip()
    if not message:
        message = f"Command failed ({cmd[0]}) with exit code {result.returncode}"
    raise click.ClickException(message)


def _latest_mtime(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        return path.stat().st_mtime
    newest = 0.0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            newest = max(newest, file_path.stat().st_mtime)
    return newest


def _frontend_needs_build(frontend_dir: Path, dist_dir: Path) -> bool:
    index_file = dist_dir / "index.html"
    if not index_file.is_file():
        return True

    dist_mtime = _latest_mtime(dist_dir)
    tracked_sources = [
        frontend_dir / "index.html",
        frontend_dir / "package.json",
        frontend_dir / "yarn.lock",
        frontend_dir / "vite.config.js",
    ]
    for file_path in tracked_sources:
        if file_path.exists() and file_path.stat().st_mtime > dist_mtime:
            return True

    src_dir = frontend_dir / "src"
    if src_dir.exists() and _latest_mtime(src_dir) > dist_mtime:
        return True

    return False


def _ensure_frontend_built(data_dir: Path) -> None:
    frontend_dir = _repo_root() / "web"
    dist_dir = frontend_dir / "dist"

    if not frontend_dir.is_dir():
        raise click.ClickException(f"Missing frontend directory: {frontend_dir}")

    if not _frontend_needs_build(frontend_dir, dist_dir):
        return

    if shutil.which("node") is None:
        raise click.ClickException("node is required to build the frontend, but was not found in PATH.")
    if shutil.which("corepack") is None:
        raise click.ClickException("corepack is required to run Yarn, but was not found in PATH.")

    env = dict(os.environ)
    env.setdefault("COREPACK_HOME", str(data_dir / ".corepack"))

    _run_cli_command(["corepack", "yarn", "install"], cwd=frontend_dir, env=env)
    _run_cli_command(["corepack", "yarn", "build"], cwd=frontend_dir, env=env)


def _frontend_not_built_page() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Codex Hub Frontend Missing</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; color: #111827; }
    pre { padding: 0.75rem; border: 1px solid #d1d5db; border-radius: 8px; background: #f9fafb; }
  </style>
</head>
<body>
  <h1>Codex Hub frontend is not built</h1>
  <p>Build the React frontend using Yarn, then restart the backend.</p>
  <pre>cd web
yarn install
yarn build</pre>
</body>
</html>
    """


def _run(cmd: list[str], cwd: Path | None = None, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=capture,
    )
    if check and result.returncode != 0:
        message = (result.stdout or "") + (result.stderr or "")
        raise HTTPException(status_code=400, detail=f"Command failed ({cmd[0]}): {message.strip()}")
    return result


def _run_logged(cmd: list[str], log_path: Path, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
        log_file.write(f"$ {' '.join(cmd)}\n")
        log_file.flush()
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=False,
            text=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        log_file.write("\n")
        log_file.flush()
    if check and result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Command failed ({cmd[0]}) with exit code {result.returncode}")
    return result


def _run_for_repo(cmd: list[str], repo_dir: Path, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(repo_dir), *cmd], capture=capture, check=check)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_state() -> dict[str, Any]:
    return {"version": 1, "projects": {}, "chats": {}}


def _empty_list(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise HTTPException(status_code=400, detail="Expected an array.")
    parsed: list[str] = []
    for raw in v:
        if not isinstance(raw, str):
            raise HTTPException(status_code=400, detail="Entries must be strings.")
        parsed.append(raw.strip())
    return [item for item in parsed if item]


def _parse_mounts(entries: list[str], direction: str) -> list[str]:
    output: list[str] = []
    for entry in entries:
        if ":" not in entry:
            raise HTTPException(status_code=400, detail=f"Invalid {direction} mount '{entry}'.")
        host, container = entry.split(":", 1)
        host_path = Path(host).expanduser()
        if not host_path.exists():
            raise HTTPException(status_code=400, detail=f"Host path for {direction} mount does not exist: {host}")
        output.append(f"{host_path}:{container}")
    return output


def _parse_env_vars(entries: list[str]) -> list[str]:
    output: list[str] = []
    for entry in entries:
        if "=" not in entry:
            raise HTTPException(status_code=400, detail=f"Invalid environment variable '{entry}'. Expected KEY=VALUE.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise HTTPException(status_code=400, detail=f"Invalid environment variable '{entry}'. Empty key.")
        if any(ch.isspace() for ch in key):
            raise HTTPException(status_code=400, detail=f"Invalid environment variable key '{key}'.")
        output.append(f"{key}={value}")
    return output


def _docker_image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _normalize_base_image_mode(mode: Any) -> str:
    if mode is None:
        return "tag"
    normalized = str(mode).strip().lower()
    if normalized in {"tag", "repo_path"}:
        return normalized
    raise HTTPException(status_code=400, detail="base_image_mode must be 'tag' or 'repo_path'.")


def _extract_repo_name(repo_url: str) -> str:
    name = repo_url.rstrip("/").split(":")[-1].rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _sanitize_workspace_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "project"


def _short_summary(text: str, max_words: int = 10, max_chars: int = 80) -> str:
    words = [part for part in text.strip().split() if part]
    if not words:
        return ""
    summary = " ".join(words[:max_words])
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"
    return summary


def _chat_preview_from_log(log_path: Path) -> tuple[str, str]:
    if not log_path.exists():
        return "", ""
    with log_path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        size = log_file.tell()
        start = size - 150_000 if size > 150_000 else 0
        log_file.seek(start)
        raw = log_file.read().decode("utf-8", errors="ignore")

    text = ANSI_ESCAPE_RE.sub("", raw).replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", ""

    user_candidates: list[str] = []
    assistant_candidates: list[str] = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if line_clean.startswith(("›", ">", "You:")):
            normalized = line_clean.lstrip("›>").strip()
            if normalized.lower().startswith("you:"):
                normalized = normalized[4:].strip()
            if normalized:
                user_candidates.append(normalized)
            continue
        if line_clean.startswith("Tip:"):
            continue
        assistant_candidates.append(line_clean)

    last_user = _short_summary(user_candidates[-1]) if user_candidates else ""
    last_assistant = _short_summary(assistant_candidates[-1], max_words=14, max_chars=120) if assistant_candidates else ""
    return last_user, last_assistant


def _default_user() -> str:
    try:
        return os.getlogin()
    except OSError:
        import pwd

        return pwd.getpwuid(os.getuid()).pw_name


def _snapshot_schema_version() -> int:
    return 2


def _docker_remove_images(prefixes: tuple[str, ...], explicit_tags: set[str]) -> None:
    if shutil.which("docker") is None:
        return

    requested: set[str] = {tag.strip() for tag in explicit_tags if str(tag).strip()}
    list_result = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        check=False,
        text=True,
        capture_output=True,
    )
    if list_result.returncode == 0:
        for raw in list_result.stdout.splitlines():
            tag = raw.strip()
            if not tag or tag == "<none>:<none>":
                continue
            if any(tag.startswith(prefix) for prefix in prefixes):
                requested.add(tag)

    if not requested:
        return

    subprocess.run(
        ["docker", "image", "rm", "-f", *sorted(requested)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _docker_fix_path_ownership(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        return
    if shutil.which("docker") is None:
        return
    if not _docker_image_exists(DEFAULT_CODEX_IMAGE):
        return
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "bash",
            "--volume",
            f"{path}:/target",
            DEFAULT_CODEX_IMAGE,
            "-lc",
            f"chown -R {uid}:{gid} /target || true; chmod -R u+rwX /target || true",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _detect_default_branch(repo_url: str) -> str:
    result = _run(["git", "ls-remote", "--symref", repo_url, "HEAD"], capture=True, check=False)
    if result.returncode != 0:
        return "master"

    for line in result.stdout.splitlines():
        if not line.startswith("ref:"):
            continue
        parts = line.replace("\t", " ").split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        if ref.startswith("refs/heads/"):
            return ref.rsplit("/", 1)[-1]

    return "master"


def _git_default_remote_branch(repo_dir: Path) -> str | None:
    result = _run_for_repo(["symbolic-ref", "refs/remotes/origin/HEAD"], repo_dir, capture=True, check=False)
    if result.returncode != 0:
        return None
    ref = result.stdout.strip()
    if not ref.startswith("refs/remotes/origin/"):
        return None
    return ref.rsplit("/", 1)[-1]


def _git_has_remote_branch(repo_dir: Path, branch: str) -> bool:
    result = _run_for_repo(["show-ref", "--verify", "--quiet", f"refs/remotes/origin/{branch}"], repo_dir, check=False)
    return result.returncode == 0


def _is_process_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return False


def _stop_process(pid: int) -> None:
    if not _is_process_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if not _is_process_running(pid):
            return
        time.sleep(0.1)
    if _is_process_running(pid):
        os.kill(pid, signal.SIGKILL)


class HubState:
    def __init__(self, data_dir: Path, config_file: Path):
        self.data_dir = data_dir
        self.config_file = config_file
        self.state_file = self.data_dir / STATE_FILE_NAME
        self.project_dir = self.data_dir / "projects"
        self.chat_dir = self.data_dir / "chats"
        self.log_dir = self.data_dir / "logs"
        self._lock = Lock()
        self._runtime_lock = Lock()
        self._project_build_lock = Lock()
        self._project_build_threads: dict[str, Thread] = {}
        self._chat_runtimes: dict[str, ChatRuntime] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.chat_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.state_file.exists():
                return _new_state()
            try:
                return json.loads(self.state_file.read_text())
            except json.JSONDecodeError:
                return _new_state()

    def save(self, state: dict[str, Any]) -> None:
        with self._lock:
            with self.state_file.open("w", encoding="utf-8") as fp:
                json.dump(state, fp, indent=2)

    def chat_workdir(self, chat_id: str) -> Path:
        chat = self.chat(chat_id)
        if chat is not None and chat.get("workspace"):
            return Path(str(chat["workspace"]))
        return self.chat_dir / chat_id

    def project_workdir(self, project_id: str) -> Path:
        return self.project_dir / project_id

    def chat_log(self, chat_id: str) -> Path:
        return self.log_dir / f"{chat_id}.log"

    def project_build_log(self, project_id: str) -> Path:
        return self.log_dir / f"project-{project_id}.log"

    def project(self, project_id: str) -> dict[str, Any] | None:
        return self.load()["projects"].get(project_id)

    def chat(self, chat_id: str) -> dict[str, Any] | None:
        return self.load()["chats"].get(chat_id)

    def list_projects(self) -> list[dict[str, Any]]:
        return list(self.load()["projects"].values())

    def list_chats(self) -> list[dict[str, Any]]:
        return list(self.load()["chats"].values())

    def add_project(
        self,
        repo_url: str,
        name: str | None = None,
        default_branch: str | None = None,
        setup_script: str | None = None,
        base_image_mode: str | None = None,
        base_image_value: str | None = None,
        default_ro_mounts: list[str] | None = None,
        default_rw_mounts: list[str] | None = None,
        default_env_vars: list[str] | None = None,
        ) -> dict[str, Any]:
        if not repo_url:
            raise HTTPException(status_code=400, detail="repo_url is required.")

        state = self.load()
        project_id = uuid.uuid4().hex
        project_name = name or _extract_repo_name(repo_url)
        project = {
            "id": project_id,
            "name": project_name,
            "repo_url": repo_url,
            "setup_script": setup_script or "",
            "base_image_mode": _normalize_base_image_mode(base_image_mode),
            "base_image_value": (base_image_value or "").strip(),
            "default_ro_mounts": default_ro_mounts or [],
            "default_rw_mounts": default_rw_mounts or [],
            "default_env_vars": default_env_vars or [],
            "default_branch": default_branch or _detect_default_branch(repo_url),
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "setup_snapshot_image": "",
            "build_status": "pending",
            "build_error": "",
            "build_started_at": "",
            "build_finished_at": "",
        }
        state["projects"][project_id] = project
        self.save(state)
        self._schedule_project_build(project_id)
        return self.load()["projects"][project_id]

    def update_project(self, project_id: str, update: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        for field in [
            "setup_script",
            "default_branch",
            "name",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
        ]:
            if field in update:
                project[field] = update[field]

        snapshot_fields = {
            "setup_script",
            "default_branch",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
        }
        requires_rebuild = any(field in update for field in snapshot_fields)
        if requires_rebuild:
            project["setup_snapshot_image"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""

        project["updated_at"] = _iso_now()
        state["projects"][project_id] = project
        self.save(state)
        if requires_rebuild:
            self._schedule_project_build(project_id)
            return self.load()["projects"][project_id]
        return self.load()["projects"][project_id]

    def _schedule_project_build(self, project_id: str) -> None:
        with self._project_build_lock:
            thread = self._project_build_threads.get(project_id)
            if thread and thread.is_alive():
                return
            thread = Thread(target=self._project_build_worker, args=(project_id,), daemon=True)
            self._project_build_threads[project_id] = thread
            thread.start()

    def _project_build_worker(self, project_id: str) -> None:
        try:
            while True:
                state = self.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                build_status = str(project.get("build_status") or "")
                if build_status not in {"pending", "building"}:
                    return
                self._build_project_snapshot(project_id)
                state = self.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                expected = self._project_setup_snapshot_tag(project)
                snapshot = str(project.get("setup_snapshot_image") or "").strip()
                status = str(project.get("build_status") or "")
                if status == "ready" and snapshot == expected and _docker_image_exists(snapshot):
                    return
                if status == "pending":
                    continue
                if status == "ready" and snapshot != expected:
                    project["build_status"] = "pending"
                    project["updated_at"] = _iso_now()
                    state["projects"][project_id] = project
                    self.save(state)
                    continue
                return
        finally:
            with self._project_build_lock:
                existing = self._project_build_threads.get(project_id)
                if existing is not None and existing.ident == current_thread().ident:
                    self._project_build_threads.pop(project_id, None)

    def _build_project_snapshot(self, project_id: str) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        started_at = _iso_now()
        project["build_status"] = "building"
        project["build_error"] = ""
        project["build_started_at"] = started_at
        project["build_finished_at"] = ""
        project["updated_at"] = started_at
        state["projects"][project_id] = project
        self.save(state)

        project_copy = dict(project)
        log_path = self.project_build_log(project_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")

        try:
            snapshot_tag = self._prepare_project_snapshot_for_project(project_copy, log_path=log_path)
        except Exception as exc:
            state = self.load()
            current = state["projects"].get(project_id)
            if current is None:
                raise
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            current["build_status"] = "failed"
            current["build_error"] = str(detail)
            current["build_finished_at"] = _iso_now()
            current["updated_at"] = _iso_now()
            state["projects"][project_id] = current
            self.save(state)
            return current

        state = self.load()
        current = state["projects"].get(project_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        current["setup_snapshot_image"] = snapshot_tag
        current["snapshot_updated_at"] = _iso_now()
        current["build_status"] = "ready"
        current["build_error"] = ""
        current["build_finished_at"] = _iso_now()
        current["updated_at"] = _iso_now()
        state["projects"][project_id] = current
        self.save(state)
        return current

    def delete_project(self, project_id: str) -> None:
        state = self.load()
        if project_id not in state["projects"]:
            raise HTTPException(status_code=404, detail="Project not found.")

        project_chats = [chat for chat in self.list_chats() if chat["project_id"] == project_id]
        for chat in project_chats:
            self.delete_chat(chat["id"], state=state)

        project_workspace = self.project_workdir(project_id)
        if project_workspace.exists():
            self._delete_path(project_workspace)
        project_log = self.project_build_log(project_id)
        if project_log.exists():
            project_log.unlink()

        del state["projects"][project_id]
        self.save(state)

    def create_chat(
        self,
        project_id: str,
        profile: str | None,
        ro_mounts: list[str],
        rw_mounts: list[str],
        env_vars: list[str],
        codex_args: list[str] | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        chat_id = uuid.uuid4().hex
        now = _iso_now()
        workspace_path = self.chat_dir / f"{_sanitize_workspace_component(project.get('name') or project_id)}_{chat_id}"
        chat = {
            "id": chat_id,
            "project_id": project_id,
            "name": f"chat-{chat_id[:8]}",
            "profile": profile or "",
            "ro_mounts": ro_mounts,
            "rw_mounts": rw_mounts,
            "env_vars": env_vars,
            "codex_args": codex_args or [],
            "status": "stopped",
            "pid": None,
            "workspace": str(workspace_path),
            "created_at": now,
            "updated_at": now,
        }
        state["chats"][chat_id] = chat
        self.save(state)
        return chat

    def create_and_start_chat(self, project_id: str) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        build_status = str(project.get("build_status") or "")
        if build_status != "ready":
            raise HTTPException(status_code=409, detail="Project image is still being built. Save settings and wait.")
        chat = self.create_chat(
            project_id,
            profile="",
            ro_mounts=list(project.get("default_ro_mounts") or []),
            rw_mounts=list(project.get("default_rw_mounts") or []),
            env_vars=list(project.get("default_env_vars") or []),
            codex_args=[],
        )
        return self.start_chat(chat["id"])

    def update_chat(self, chat_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        for field in ["name", "profile", "ro_mounts", "rw_mounts", "env_vars", "codex_args"]:
            if field in patch:
                chat[field] = patch[field]

        chat["updated_at"] = _iso_now()
        state["chats"][chat_id] = chat
        self.save(state)
        return chat

    def delete_chat(self, chat_id: str, state: dict[str, Any] | None = None) -> None:
        local_state = state or self.load()
        chat = local_state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        pid = chat.get("pid")
        if isinstance(pid, int):
            _stop_process(pid)
        self._close_runtime(chat_id)

        workspace = Path(str(chat.get("workspace") or self.chat_dir / chat_id))
        if workspace.exists():
            self._delete_path(workspace)

        local_state["chats"].pop(chat_id, None)
        if state is None:
            self.save(local_state)
        else:
            state["chats"] = local_state["chats"]

    def _delete_path(self, path: Path) -> None:
        if not path.exists():
            return
        shutil.rmtree(path)

    @staticmethod
    def _queue_put(listener: queue.Queue[str | None], value: str | None) -> None:
        try:
            listener.put_nowait(value)
            return
        except queue.Full:
            pass

        try:
            listener.get_nowait()
        except queue.Empty:
            return

        try:
            listener.put_nowait(value)
        except queue.Full:
            return

    def _pop_runtime(self, chat_id: str) -> ChatRuntime | None:
        with self._runtime_lock:
            return self._chat_runtimes.pop(chat_id, None)

    def _close_runtime(self, chat_id: str) -> None:
        runtime = self._pop_runtime(chat_id)
        if runtime is None:
            return
        listeners = list(runtime.listeners)
        runtime.listeners.clear()
        try:
            os.close(runtime.master_fd)
        except OSError:
            pass
        for listener in listeners:
            self._queue_put(listener, None)

    def _runtime_for_chat(self, chat_id: str) -> ChatRuntime | None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
        if runtime is None:
            return None
        if _is_process_running(runtime.process.pid):
            return runtime
        self._close_runtime(chat_id)
        return None

    def _broadcast_runtime_output(self, chat_id: str, text: str) -> None:
        if not text:
            return
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
            listeners = list(runtime.listeners) if runtime else []
        for listener in listeners:
            self._queue_put(listener, text)

    def _runtime_reader_loop(self, chat_id: str, master_fd: int, log_path: Path) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab") as log_file:
                while True:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    log_file.write(chunk)
                    log_file.flush()
                    decoded = decoder.decode(chunk)
                    if decoded:
                        self._broadcast_runtime_output(chat_id, decoded)
                tail = decoder.decode(b"", final=True)
                if tail:
                    self._broadcast_runtime_output(chat_id, tail)
        finally:
            runtime = self._pop_runtime(chat_id)
            listeners = list(runtime.listeners) if runtime else []
            if runtime:
                runtime.listeners.clear()
            try:
                os.close(master_fd)
            except OSError:
                pass
            for listener in listeners:
                self._queue_put(listener, None)

    def _register_runtime(self, chat_id: str, process: subprocess.Popen, master_fd: int) -> None:
        previous = self._pop_runtime(chat_id)
        if previous is not None:
            try:
                os.close(previous.master_fd)
            except OSError:
                pass
            for listener in list(previous.listeners):
                self._queue_put(listener, None)

        with self._runtime_lock:
            self._chat_runtimes[chat_id] = ChatRuntime(process=process, master_fd=master_fd)

        reader_thread = Thread(
            target=self._runtime_reader_loop,
            args=(chat_id, master_fd, self.chat_log(chat_id)),
            daemon=True,
        )
        reader_thread.start()

    def _spawn_chat_process(self, chat_id: str, cmd: list[str]) -> subprocess.Popen:
        master_fd, slave_fd = os.openpty()
        try:
            self._set_terminal_size(slave_fd, DEFAULT_PTY_COLS, DEFAULT_PTY_ROWS)
            proc = subprocess.Popen(
                cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                os.close(slave_fd)
            except OSError:
                pass
            raise

        try:
            os.close(slave_fd)
        except OSError:
            pass

        self._register_runtime(chat_id, proc, master_fd)
        return proc

    @staticmethod
    def _set_terminal_size(fd: int, cols: int, rows: int) -> None:
        safe_cols = max(1, int(cols))
        safe_rows = max(1, int(rows))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", safe_rows, safe_cols, 0, 0))

    def _chat_log_tail(self, chat_id: str, max_bytes: int = TERMINAL_LOG_TAIL_BYTES) -> str:
        log_path = self.chat_log(chat_id)
        if not log_path.exists():
            return ""
        with log_path.open("rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            start = size - max_bytes if size > max_bytes else 0
            log_file.seek(start)
            content = log_file.read()
        return content.decode("utf-8", errors="ignore")

    def attach_terminal(self, chat_id: str) -> tuple[queue.Queue[str | None], str]:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        listener: queue.Queue[str | None] = queue.Queue(maxsize=TERMINAL_QUEUE_MAX)
        with self._runtime_lock:
            active_runtime = self._chat_runtimes.get(chat_id)
            if active_runtime is None:
                raise HTTPException(status_code=409, detail="Chat is not running.")
            active_runtime.listeners.add(listener)
        return listener, self._chat_log_tail(chat_id)

    def detach_terminal(self, chat_id: str, listener: queue.Queue[str | None]) -> None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
            if runtime is None:
                return
            runtime.listeners.discard(listener)

    def write_terminal_input(self, chat_id: str, data: str) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        if not data:
            return
        try:
            os.write(runtime.master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as exc:
            raise HTTPException(status_code=409, detail="Failed to write to chat terminal.") from exc

    def resize_terminal(self, chat_id: str, cols: int, rows: int) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        try:
            self._set_terminal_size(runtime.master_fd, cols, rows)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid terminal resize request.") from exc

    def clean_start(self) -> dict[str, int]:
        state = self.load()

        with self._runtime_lock:
            runtime_ids = list(self._chat_runtimes.keys())
        for chat_id in runtime_ids:
            self._close_runtime(chat_id)

        stopped_chats = 0
        image_tags: set[str] = set()
        for chat in state["chats"].values():
            pid = chat.get("pid")
            if isinstance(pid, int) and _is_process_running(pid):
                _stop_process(pid)
                stopped_chats += 1
            snapshot_tag = str(chat.get("setup_snapshot_image") or "").strip()
            if snapshot_tag:
                image_tags.add(snapshot_tag)

        projects_reset = 0
        for project in state["projects"].values():
            snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
            if snapshot_tag:
                image_tags.add(snapshot_tag)
            if project.get("setup_snapshot_image"):
                projects_reset += 1
            project["setup_snapshot_image"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""
            project["updated_at"] = _iso_now()

        cleared_chats = len(state["chats"])
        state["chats"] = {}

        for path in [self.chat_dir, self.project_dir, self.log_dir]:
            if path.exists():
                try:
                    shutil.rmtree(path)
                except PermissionError:
                    _docker_fix_path_ownership(path, os.getuid(), os.getgid())
                    shutil.rmtree(path)
            path.mkdir(parents=True, exist_ok=True)

        self.save(state)
        _docker_remove_images(("codex-hub-setup-", "codex-base-"), image_tags)

        return {
            "stopped_chats": stopped_chats,
            "cleared_chats": cleared_chats,
            "projects_reset": projects_reset,
            "docker_images_requested": len(image_tags),
        }

    def _ensure_chat_clone(self, chat: dict[str, Any], project: dict[str, Any]) -> Path:
        workspace = Path(str(chat.get("workspace") or self.chat_dir / chat["id"]))
        if workspace.exists():
            git_dir = workspace / ".git"
            if git_dir.is_dir():
                return workspace
            self._delete_path(workspace)

            workspace = Path(str(chat.get("workspace") or self.chat_dir / chat["id"]))

        workspace.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", project["repo_url"], str(workspace)], check=True)
        return workspace

    def _ensure_project_clone(self, project: dict[str, Any]) -> Path:
        workspace = self.project_workdir(project["id"])
        if workspace.exists():
            git_dir = workspace / ".git"
            if git_dir.is_dir():
                return workspace
            self._delete_path(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", project["repo_url"], str(workspace)], check=True)
        return workspace

    def _sync_checkout_to_remote(self, workspace: Path, project: dict[str, Any]) -> None:
        _run_for_repo(["fetch", "--all", "--prune"], workspace, check=True)
        branch = project.get("default_branch") or "master"
        remote_default = _git_default_remote_branch(workspace)
        if remote_default:
            branch = remote_default

        if not _git_has_remote_branch(workspace, branch):
            branch = "main" if _git_has_remote_branch(workspace, "main") else "master"

        if not _git_has_remote_branch(workspace, branch):
            raise HTTPException(status_code=400, detail="Unable to determine remote branch for sync.")

        _run_for_repo(["checkout", branch], workspace, check=True)
        _run_for_repo(["reset", "--hard", f"origin/{branch}"], workspace, check=True)
        _run_for_repo(["clean", "-fd"], workspace, check=True)

    def _resolve_project_base_value(self, workspace: Path, project: dict[str, Any]) -> tuple[str, str] | None:
        base_mode = _normalize_base_image_mode(project.get("base_image_mode"))
        base_value = str(project.get("base_image_value") or "").strip()
        if not base_value:
            return None

        if base_mode == "tag":
            return "base-image", base_value

        workspace_root = workspace.resolve()
        base_candidate = Path(base_value)
        if base_candidate.is_absolute():
            resolved_base = base_candidate.resolve()
        else:
            resolved_base = (workspace / base_candidate).resolve()
        try:
            resolved_base.relative_to(workspace_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Base path must be inside the checked-out project. "
                    f"Got: {base_value}"
                ),
            ) from exc
        if not resolved_base.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Base path does not exist in project workspace: {base_value}",
            )
        if not (resolved_base.is_file() or resolved_base.is_dir()):
            raise HTTPException(
                status_code=400,
                detail=f"Base path must be a file or directory: {base_value}",
            )
        return "base", str(resolved_base)

    def _append_project_base_args(self, cmd: list[str], workspace: Path, project: dict[str, Any]) -> None:
        resolved = self._resolve_project_base_value(workspace, project)
        if not resolved:
            return
        flag, value = resolved
        cmd.extend([f"--{flag}", value])

    def _project_setup_snapshot_tag(self, project: dict[str, Any]) -> str:
        project_id = str(project.get("id") or "")[:12] or "project"
        payload = json.dumps(
            {
                "snapshot_schema_version": _snapshot_schema_version(),
                "project_id": project.get("id"),
                "setup_script": str(project.get("setup_script") or ""),
                "base_mode": _normalize_base_image_mode(project.get("base_image_mode")),
                "base_value": str(project.get("base_image_value") or ""),
                "default_ro_mounts": list(project.get("default_ro_mounts") or []),
                "default_rw_mounts": list(project.get("default_rw_mounts") or []),
                "default_env_vars": list(project.get("default_env_vars") or []),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"codex-hub-setup-{project_id}-{digest}"

    def _ensure_project_setup_snapshot(
        self,
        workspace: Path,
        project: dict[str, Any],
        log_path: Path | None = None,
    ) -> str:
        setup_script = str(project.get("setup_script") or "").strip()
        snapshot_tag = self._project_setup_snapshot_tag(project)
        if _docker_image_exists(snapshot_tag):
            if log_path is not None:
                with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
                    log_file.write(f"Using cached setup snapshot image '{snapshot_tag}'\n")
            return snapshot_tag

        cmd = [
            "uv",
            "run",
            "--project",
            str(_repo_root()),
            "codex_image",
            "--project",
            str(workspace),
            "--config-file",
            str(self.config_file),
        ]
        self._append_project_base_args(cmd, workspace, project)
        for mount in project.get("default_ro_mounts") or []:
            cmd.extend(["--ro-mount", mount])
        for mount in project.get("default_rw_mounts") or []:
            cmd.extend(["--rw-mount", mount])
        for env_entry in project.get("default_env_vars") or []:
            cmd.extend(["--env-var", env_entry])
        cmd.extend(
            [
                "--snapshot-image-tag",
                snapshot_tag,
                "--setup-script",
                setup_script,
                "--prepare-snapshot-only",
            ]
        )
        if log_path is None:
            _run(cmd, check=True)
        else:
            _run_logged(cmd, log_path=log_path, check=True)
        return snapshot_tag

    def _prepare_project_snapshot_for_project(self, project: dict[str, Any], log_path: Path | None = None) -> str:
        workspace = self._ensure_project_clone(project)
        self._sync_checkout_to_remote(workspace, project)
        return self._ensure_project_setup_snapshot(workspace, project, log_path=log_path)

    def state_payload(self) -> dict[str, Any]:
        state = self.load()
        project_map: dict[str, dict[str, Any]] = {}
        for pid, project in state["projects"].items():
            project_copy = dict(project)
            project_copy["base_image_mode"] = _normalize_base_image_mode(project_copy.get("base_image_mode"))
            project_copy["base_image_value"] = str(project_copy.get("base_image_value") or "")
            project_copy["default_ro_mounts"] = list(project_copy.get("default_ro_mounts") or [])
            project_copy["default_rw_mounts"] = list(project_copy.get("default_rw_mounts") or [])
            project_copy["default_env_vars"] = list(project_copy.get("default_env_vars") or [])
            project_copy["setup_snapshot_image"] = str(project_copy.get("setup_snapshot_image") or "")
            project_copy["build_status"] = str(project_copy.get("build_status") or "pending")
            project_copy["build_error"] = str(project_copy.get("build_error") or "")
            project_copy["build_started_at"] = str(project_copy.get("build_started_at") or "")
            project_copy["build_finished_at"] = str(project_copy.get("build_finished_at") or "")
            project_map[pid] = project_copy
        chats = []
        dead_chat_ids: list[str] = []
        should_save = False
        for chat_id, chat in list(state["chats"].items()):
            chat_copy = dict(chat)
            pid = chat_copy.get("pid")
            chat_copy["ro_mounts"] = list(chat_copy.get("ro_mounts") or [])
            chat_copy["rw_mounts"] = list(chat_copy.get("rw_mounts") or [])
            chat_copy["env_vars"] = list(chat_copy.get("env_vars") or [])
            chat_copy["setup_snapshot_image"] = str(chat_copy.get("setup_snapshot_image") or "")
            running = _is_process_running(pid)
            if running:
                chat_copy["status"] = "running"
            else:
                dead_chat_ids.append(chat_id)
                self._close_runtime(chat_id)
                was_running = str(chat_copy.get("status") or "") == "running" or isinstance(pid, int)
                if was_running:
                    continue
                dead_chat_ids.pop()
                chat_copy["status"] = "stopped"
                if chat_copy.get("pid") is not None:
                    chat_copy["pid"] = None
                    if chat_id in state["chats"]:
                        state["chats"][chat_id]["pid"] = None
                        state["chats"][chat_id]["status"] = "stopped"
                        should_save = True
            chat_copy["is_running"] = running
            chat_copy["container_workspace"] = f"/home/{_default_user()}/projects/{Path(str(chat_copy['workspace'])).name}"
            chat_copy["project_name"] = project_map.get(chat_copy["project_id"], {}).get("name", "Unknown")
            title, subtitle = _chat_preview_from_log(self.chat_log(chat_id))
            chat_copy["display_name"] = title or chat_copy["name"]
            chat_copy["display_subtitle"] = subtitle
            chats.append(chat_copy)

        if dead_chat_ids:
            for chat_id in dead_chat_ids:
                self.delete_chat(chat_id, state=state)
            should_save = True
        if should_save:
            self.save(state)

        state["chats"] = chats
        state["projects"] = list(project_map.values())
        return state

    def start_chat(self, chat_id: str) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat["project_id"])
        if project is None:
            raise HTTPException(status_code=404, detail="Parent project missing.")

        if chat.get("status") == "running" and _is_process_running(chat.get("pid")):
            raise HTTPException(status_code=409, detail="Chat is already running.")

        build_status = str(project.get("build_status") or "")
        snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
        expected_snapshot_tag = self._project_setup_snapshot_tag(project)
        snapshot_ready = (
            build_status == "ready"
            and snapshot_tag
            and snapshot_tag == expected_snapshot_tag
            and _docker_image_exists(snapshot_tag)
        )
        if not snapshot_ready:
            raise HTTPException(status_code=409, detail="Project image is not ready yet. Wait for setup build to finish.")

        workspace = self._ensure_chat_clone(chat, project)
        self._sync_checkout_to_remote(workspace, project)

        cmd = [
            "uv",
            "run",
            "--project",
            str(_repo_root()),
            "codex_image",
            "--project",
            str(workspace),
            "--config-file",
            str(self.config_file),
        ]
        self._append_project_base_args(cmd, workspace, project)
        cmd.extend(["--snapshot-image-tag", snapshot_tag])
        for mount in chat.get("ro_mounts") or []:
            cmd.extend(["--ro-mount", mount])
        for mount in chat.get("rw_mounts") or []:
            cmd.extend(["--rw-mount", mount])
        for env_entry in chat.get("env_vars") or []:
            cmd.extend(["--env-var", env_entry])

        proc = self._spawn_chat_process(chat_id, cmd)
        chat["status"] = "running"
        chat["pid"] = proc.pid
        chat["setup_snapshot_image"] = snapshot_tag or ""
        chat["container_workspace"] = f"/home/{_default_user()}/projects/{workspace.name}"
        chat["last_started_at"] = _iso_now()
        chat["updated_at"] = _iso_now()
        state["chats"][chat_id] = chat
        self.save(state)
        return chat

    def close_chat(self, chat_id: str) -> dict[str, Any]:
        chat = self.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self.delete_chat(chat_id)
        return {"id": chat_id, "status": "deleted"}


def _html_page() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <title>Codex Hub</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d7dce3;
      --line-strong: #c7ced9;
      --text: #0f1722;
      --muted: #627082;
      --accent: #10a37f;
      --accent-strong: #0f8a6d;
      --header: #0b1017;
      --header-subtitle: #c8d0dc;
      --pill-running: #0f9b65;
      --pill-stopped: #6b7280;
      --shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0a1018;
        --panel: #111923;
        --line: #2a3848;
        --line-strong: #32465d;
        --text: #e6edf7;
        --muted: #9aa8bb;
        --accent: #19b88e;
        --accent-strong: #16a480;
        --header: #060b11;
        --header-subtitle: #9fb1c6;
        --pill-running: #12b375;
        --pill-stopped: #738197;
        --shadow: 0 10px 24px rgba(0, 0, 0, 0.3);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: "Sohne", "Soehne", "Avenir Next", "Inter", "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    header {
      padding: 1.1rem 1.5rem;
      color: #fff;
      background: var(--header);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    h1 { margin: 0; font-size: 1.35rem; letter-spacing: -0.02em; font-weight: 650; }
    .subhead { margin-top: 0.2rem; color: var(--header-subtitle); font-size: 0.92rem; }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 1rem;
      display: grid;
      gap: 1rem;
      grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
      align-items: start;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1rem;
      box-shadow: var(--shadow);
    }
    section h2 { margin-top: 0; }
    .grid { display: grid; gap: 0.6rem; }
    input, textarea, button, select {
      width: 100%;
      padding: 0.58rem 0.62rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font: inherit;
    }
    input:focus, textarea:focus, select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.18);
    }
    textarea {
      min-height: 84px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
      line-height: 1.35;
    }
    .script-input { min-height: 132px; }
    .row { display: grid; grid-template-columns: 2fr 1fr; gap: 0.6rem; }
    .row.base-row { grid-template-columns: 1fr 2fr; }
    .chat {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.8rem;
      margin-bottom: 0.85rem;
      background: var(--panel);
    }
    .chat h3 { margin: 0 0 0.4rem 0; }
    .meta { font-size: 0.85rem; color: var(--muted); }
    .pill { padding: 0.12rem 0.5rem; border-radius: 999px; font-size: 0.75rem; color: #fff; background: #607d8b; font-weight: 600; }
    .running { background: var(--pill-running); }
    .stopped { background: var(--pill-stopped); }
    .controls { display: flex; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap; }
    button {
      cursor: pointer;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 600;
      transition: background 120ms ease, border-color 120ms ease;
    }
    button:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    .controls button { width: auto; }
    .inline-controls { display: flex; gap: 0.45rem; align-items: center; flex-wrap: wrap; }
    .inline-controls button { width: auto; }
    .widget-list { display: grid; gap: 0.5rem; }
    .widget-row {
      display: grid;
      gap: 0.5rem;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0.5rem;
      background: color-mix(in srgb, var(--panel) 94%, transparent);
    }
    .widget-row.volume { grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) 130px auto; }
    .widget-row.env { grid-template-columns: minmax(140px, 0.8fr) minmax(220px, 1fr) auto; }
    .widget-row button { width: auto; }
    .small { padding: 0.42rem 0.56rem; font-size: 0.85rem; }
    .section-label { font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem; }
    .error-banner {
      display: none;
      margin: 0 1rem;
      padding: 0.6rem 0.75rem;
      border-radius: 8px;
      border: 1px solid #f3b2ad;
      color: #7a1610;
      background: #fff0ef;
      font-size: 0.9rem;
    }
    button.secondary {
      background: transparent;
      color: var(--text);
      border-color: var(--line-strong);
    }
    button.secondary:hover {
      background: rgba(127, 127, 127, 0.08);
      border-color: var(--line-strong);
    }
    button.danger {
      background: #b42318;
      border-color: #b42318;
      color: #fff;
    }
    button.danger:hover {
      background: #9f1f15;
      border-color: #9f1f15;
    }
    .muted { color: var(--muted); }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
      .widget-row.volume { grid-template-columns: 1fr; }
      .widget-row.env { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Codex Hub</h1>
    <div class="subhead">Project-level workspaces, one cloned directory per chat</div>
  </header>
  <div id="ui-error" class="error-banner"></div>
  <main>
    <section>
      <h2>Projects</h2>
      <form id="project-form" class="grid" onsubmit="createProject(event)">
        <input id="project-repo" required placeholder="git@github.com:org/repo.git or https://..." />
        <div class="row">
          <input id="project-name" placeholder="Optional project name" />
          <input id="project-branch" placeholder="Default branch (optional, auto-detect)" />
        </div>
        <div class="row base-row">
          <select id="project-base-image-mode" onchange="updateBasePlaceholderForCreate()">
            <option value="tag">Docker image tag</option>
            <option value="repo_path">Repo Dockerfile/path</option>
          </select>
          <input id="project-base-image-value" placeholder="Docker image tag (e.g. nvcr.io/nvidia/isaac-lab:2.3.2)" />
        </div>
        <textarea id="project-setup-script" class="script-input" placeholder="Setup script (one command per line, run in the checked-out project)&#10;example:&#10;uv sync&#10;uv run python -m pip install -e ."></textarea>
        <div class="section-label">Default volumes for new chats</div>
        <div id="project-default-volumes" class="widget-list"></div>
        <div class="inline-controls">
          <button type="button" class="secondary small" onclick="addVolumeRow('project-default-volumes')">Add volume</button>
        </div>
        <div class="section-label">Default environment variables for new chats</div>
        <div id="project-default-env" class="widget-list"></div>
        <div class="inline-controls">
          <button type="button" class="secondary small" onclick="addEnvRow('project-default-env')">Add environment variable</button>
        </div>
        <button type="submit">Add project</button>
      </form>
      <h2 style="margin-top:1rem;">Projects</h2>
      <div id="projects"></div>
    </section>
    <section>
      <h2>Chats</h2>
      <div id="chats"></div>
    </section>
  </main>
  <script>
    async function fetchJson(url, options={}) {
      const response = await fetch(url, Object.assign({ headers: { "Content-Type":"application/json" } }, options));
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed with ${response.status}`);
      }
      if (response.status === 204) return null;
      return response.json();
    }

    async function fetchText(url) {
      const response = await fetch(url);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed with ${response.status}`);
      }
      return response.text();
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function normalizeBaseMode(mode) {
      return mode === 'repo_path' ? 'repo_path' : 'tag';
    }

    function baseModeLabel(mode) {
      return mode === 'repo_path' ? 'Repo path' : 'Docker tag';
    }

    function baseInputPlaceholder(mode) {
      if (mode === 'repo_path') {
        return 'Path in repo to Dockerfile or dir (e.g. docker/base or docker/base/Dockerfile)';
      }
      return 'Docker image tag (e.g. nvcr.io/nvidia/isaac-lab:2.3.2)';
    }

    function updateBasePlaceholderForCreate() {
      const mode = normalizeBaseMode(document.getElementById('project-base-image-mode').value);
      const input = document.getElementById('project-base-image-value');
      input.placeholder = baseInputPlaceholder(mode);
    }

    function updateBasePlaceholderForProject(projectId) {
      const mode = normalizeBaseMode(document.getElementById(`base-mode-${projectId}`).value);
      const input = document.getElementById(`base-value-${projectId}`);
      input.placeholder = baseInputPlaceholder(mode);
    }

    function addVolumeRow(listId, mount = null, markDirty = true) {
      const list = document.getElementById(listId);
      if (!list) return;
      if (markDirty) uiDirty = true;
      const mode = mount && mount.mode === 'ro' ? 'ro' : 'rw';
      const host = escapeHtml((mount && mount.host) || '');
      const container = escapeHtml((mount && mount.container) || '');
      const row = document.createElement('div');
      row.className = 'widget-row volume';
      row.innerHTML = `
        <input class="vol-host" placeholder="Local path (e.g. /data/datasets)" value="${host}" />
        <input class="vol-container" placeholder="Container path (e.g. /workspace/data)" value="${container}" />
        <select class="vol-mode">
          <option value="rw" ${mode === 'rw' ? 'selected' : ''}>Read-write</option>
          <option value="ro" ${mode === 'ro' ? 'selected' : ''}>Read-only</option>
        </select>
        <button type="button" class="secondary small" onclick="removeWidgetRow(this)">Remove</button>
      `;
      list.appendChild(row);
    }

    function addEnvRow(listId, envVar = null, markDirty = true) {
      const list = document.getElementById(listId);
      if (!list) return;
      if (markDirty) uiDirty = true;
      const key = escapeHtml((envVar && envVar.key) || '');
      const value = escapeHtml((envVar && envVar.value) || '');
      const row = document.createElement('div');
      row.className = 'widget-row env';
      row.innerHTML = `
        <input class="env-key" placeholder="KEY" value="${key}" />
        <input class="env-value" placeholder="VALUE" value="${value}" />
        <button type="button" class="secondary small" onclick="removeWidgetRow(this)">Remove</button>
      `;
      list.appendChild(row);
    }

    function removeWidgetRow(buttonEl) {
      const row = buttonEl.closest('.widget-row');
      if (row) {
        row.remove();
        uiDirty = true;
      }
    }

    function parseMountEntry(spec, mode) {
      if (typeof spec !== 'string') return null;
      const idx = spec.indexOf(':');
      if (idx <= 0 || idx === spec.length - 1) return null;
      return {
        host: spec.slice(0, idx),
        container: spec.slice(idx + 1),
        mode: mode === 'ro' ? 'ro' : 'rw',
      };
    }

    function seedVolumeRows(listId, roMounts = [], rwMounts = []) {
      const list = document.getElementById(listId);
      if (!list) return;
      list.innerHTML = '';
      const all = [];
      (roMounts || []).forEach((spec) => {
        const parsed = parseMountEntry(spec, 'ro');
        if (parsed) all.push(parsed);
      });
      (rwMounts || []).forEach((spec) => {
        const parsed = parseMountEntry(spec, 'rw');
        if (parsed) all.push(parsed);
      });
      all.forEach((entry) => addVolumeRow(listId, entry, false));
    }

    function splitEnvVar(entry) {
      if (typeof entry !== 'string') return { key: '', value: '' };
      const idx = entry.indexOf('=');
      if (idx < 0) return { key: entry, value: '' };
      return { key: entry.slice(0, idx), value: entry.slice(idx + 1) };
    }

    function seedEnvRows(listId, envVars = []) {
      const list = document.getElementById(listId);
      if (!list) return;
      list.innerHTML = '';
      (envVars || []).forEach((entry) => addEnvRow(listId, splitEnvVar(entry), false));
    }

    function collectMountPayload(listId) {
      const list = document.getElementById(listId);
      const ro = [];
      const rw = [];
      if (!list) return { ro_mounts: ro, rw_mounts: rw };

      list.querySelectorAll('.widget-row.volume').forEach((row) => {
        const hostEl = row.querySelector('.vol-host');
        const containerEl = row.querySelector('.vol-container');
        const modeEl = row.querySelector('.vol-mode');
        const host = (hostEl ? hostEl.value : '').trim();
        const container = (containerEl ? containerEl.value : '').trim();
        const mode = modeEl && modeEl.value === 'ro' ? 'ro' : 'rw';
        if (!host && !container) return;
        if (!host || !container) {
          throw new Error('Each volume needs both local and container path.');
        }
        const entry = `${host}:${container}`;
        if (mode === 'ro') ro.push(entry);
        else rw.push(entry);
      });

      return { ro_mounts: ro, rw_mounts: rw };
    }

    function collectEnvPayload(listId) {
      const list = document.getElementById(listId);
      const envVars = [];
      if (!list) return envVars;

      list.querySelectorAll('.widget-row.env').forEach((row) => {
        const keyEl = row.querySelector('.env-key');
        const valueEl = row.querySelector('.env-value');
        const key = (keyEl ? keyEl.value : '').trim();
        const value = valueEl ? valueEl.value : '';
        if (!key && !value) return;
        if (!key) {
          throw new Error('Environment variable key is required when value is provided.');
        }
        envVars.push(`${key}=${value}`);
      });

      return envVars;
    }

    function isEditingFormField() {
      const active = document.activeElement;
      if (!active) return false;
      const tag = (active.tagName || '').toLowerCase();
      return tag === 'input' || tag === 'textarea' || tag === 'select';
    }

    let hasRenderedOnce = false;
    let uiDirty = false;

    document.addEventListener('input', (event) => {
      if (event.target && event.target.closest('.widget-list')) {
        uiDirty = true;
      }
    });

    async function refresh() {
      if (hasRenderedOnce && (isEditingFormField() || uiDirty)) {
        return;
      }
      const errorEl = document.getElementById('ui-error');
      const projects = document.getElementById('projects');
      const chats = document.getElementById('chats');

      try {
        const state = await fetchJson('/api/state');
        errorEl.style.display = 'none';
        errorEl.textContent = '';

        projects.innerHTML = '';
        chats.innerHTML = '';

        state.projects.forEach(project => {
        const projectName = escapeHtml(project.name || 'Unnamed project');
        const projectId = escapeHtml(project.id || '');
        const projectBranch = escapeHtml(project.default_branch || 'master');
        const projectRepo = escapeHtml(project.repo_url || '');
        const setupScriptRaw = String(project.setup_script || '');
        const setupScript = escapeHtml(setupScriptRaw);
        const setupCommandCount = setupScriptRaw.split('\\n').map(line => line.trim()).filter(Boolean).length;
        const baseMode = normalizeBaseMode(project.base_image_mode);
        const baseValueRaw = String(project.base_image_value || '');
        const baseValue = escapeHtml(baseValueRaw);
        const baseSummary = baseValueRaw
          ? `${baseModeLabel(baseMode)}: ${escapeHtml(baseValueRaw)}`
          : 'Default codex_image base image';
        const defaultVolumeCount = (project.default_ro_mounts || []).length + (project.default_rw_mounts || []).length;
        const defaultEnvCount = (project.default_env_vars || []).length;

        const card = document.createElement('div');
        card.className = 'chat';
        card.innerHTML = `
          <h3>${projectName}</h3>
          <div class="meta">ID: ${projectId}</div>
          <div class="meta">Branch: ${projectBranch}</div>
          <div class="meta">Setup commands: ${setupCommandCount}</div>
          <div class="meta">Base image source: ${baseSummary}</div>
          <div class="meta">Default volumes: ${defaultVolumeCount} | Default env vars: ${defaultEnvCount}</div>
          <div class="grid" style="margin-top:0.5rem;">
            <input value="${projectRepo}" placeholder="Repo URL" id="repo-${project.id}" disabled />
            <div class="row">
              <input id="profile-${project.id}" placeholder="Profile (e.g. fast)" />
              <button onclick="createChatForProject('${project.id}')">Start new chat</button>
            </div>
            <div class="row base-row">
              <select id="base-mode-${project.id}" onchange="updateBasePlaceholderForProject('${project.id}')">
                <option value="tag" ${baseMode === 'tag' ? 'selected' : ''}>Docker image tag</option>
                <option value="repo_path" ${baseMode === 'repo_path' ? 'selected' : ''}>Repo Dockerfile/path</option>
              </select>
              <input id="base-value-${project.id}" value="${baseValue}" placeholder="${escapeHtml(baseInputPlaceholder(baseMode))}" />
            </div>
            <textarea id="setup-${project.id}" class="script-input" placeholder="One command per line; executed sequentially in workspace">${setupScript}</textarea>
            <button onclick="saveProjectSettings('${project.id}')">Save project settings</button>
            <div class="section-label">Default volumes for new chats</div>
            <div id="new-volumes-${project.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addVolumeRow('new-volumes-${project.id}')">Add volume</button>
            </div>
            <div class="section-label">Default environment variables for new chats</div>
            <div id="new-env-${project.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addEnvRow('new-env-${project.id}')">Add environment variable</button>
            </div>
          </div>
          <div class="controls">
            <button class="danger" onclick="deleteProject('${project.id}')">Delete project</button>
          </div>
        `;
        projects.appendChild(card);
        seedVolumeRows(`new-volumes-${project.id}`, project.default_ro_mounts || [], project.default_rw_mounts || []);
        seedEnvRows(`new-env-${project.id}`, project.default_env_vars || []);
        });

        state.chats.forEach(chat => {
        const chatName = escapeHtml(chat.name || 'Unnamed chat');
        const chatProjectName = escapeHtml(chat.project_name || 'Unknown');
        const chatId = escapeHtml(chat.id || '');
        const chatProfile = escapeHtml(chat.profile || 'default');
        const chatProfileInput = escapeHtml(chat.profile || '');
        const workspace = escapeHtml(chat.workspace || '');
        const containerWorkspace = escapeHtml(chat.container_workspace || 'not started yet');
        const volumeCount = (chat.ro_mounts || []).length + (chat.rw_mounts || []).length;
        const envCount = (chat.env_vars || []).length;
        const card = document.createElement('div');
        card.className = 'chat';
        const pill = chat.is_running ? 'running' : 'stopped';
        card.innerHTML = `
          <h3>${chatName}</h3>
          <div class="meta"><span class="pill ${pill}">${chat.status}</span> ${chatProjectName}</div>
          <div class="meta">Chat ID: ${chatId}</div>
          <div class="meta">Profile: ${chatProfile}</div>
          <div class="meta">Workspace: ${workspace}</div>
          <div class="meta">Container folder: ${containerWorkspace}</div>
          <div class="meta">Volumes: ${volumeCount} | Env vars: ${envCount}</div>
          <div class="grid" style="margin-top:0.5rem;">
            <input id="chat-profile-${chat.id}" value="${chatProfileInput}" placeholder="Profile" />
            <div class="section-label">Volumes</div>
            <div id="chat-volumes-${chat.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addVolumeRow('chat-volumes-${chat.id}')">Add volume</button>
            </div>
            <div class="section-label">Environment variables</div>
            <div id="chat-env-${chat.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addEnvRow('chat-env-${chat.id}')">Add environment variable</button>
            </div>
          </div>
          <div class="controls">
            <button onclick="updateChat('${chat.id}')">Save config</button>
            ${chat.is_running ? `<button class="secondary" onclick="closeChat('${chat.id}')">Close</button>` : `<button onclick="startChat('${chat.id}')">Start</button>`}
            <button class="danger" onclick="deleteChat('${chat.id}')">Delete</button>
            <button class="secondary" onclick="viewLog('${chat.id}')">View logs</button>
          </div>
          <div id="log-${chat.id}" class="muted" style="white-space: pre-wrap; margin-top:0.5rem;"></div>
        `;
        chats.appendChild(card);
        seedVolumeRows(`chat-volumes-${chat.id}`, chat.ro_mounts || [], chat.rw_mounts || []);
        seedEnvRows(`chat-env-${chat.id}`, chat.env_vars || []);
        });

        hasRenderedOnce = true;
      } catch (err) {
        errorEl.style.display = 'block';
        errorEl.textContent = err && err.message ? err.message : String(err);
      }
    }

    async function createProject(event) {
      event.preventDefault();
      let defaultMounts;
      let defaultEnv;
      try {
        defaultMounts = collectMountPayload('project-default-volumes');
        defaultEnv = collectEnvPayload('project-default-env');
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        repo_url: document.getElementById('project-repo').value,
        name: document.getElementById('project-name').value,
        default_branch: document.getElementById('project-branch').value,
        base_image_mode: document.getElementById('project-base-image-mode').value,
        base_image_value: document.getElementById('project-base-image-value').value,
        setup_script: document.getElementById('project-setup-script').value,
        default_ro_mounts: defaultMounts.ro_mounts,
        default_rw_mounts: defaultMounts.rw_mounts,
        default_env_vars: defaultEnv,
      };
      await fetchJson('/api/projects', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('project-form').reset();
      updateBasePlaceholderForCreate();
      uiDirty = false;
      seedVolumeRows('project-default-volumes', [], []);
      seedEnvRows('project-default-env', []);
      await refresh();
    }

    async function saveProjectSettings(projectId) {
      let defaultMounts;
      let defaultEnv;
      try {
        defaultMounts = collectMountPayload(`new-volumes-${projectId}`);
        defaultEnv = collectEnvPayload(`new-env-${projectId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        base_image_mode: document.getElementById(`base-mode-${projectId}`).value,
        base_image_value: document.getElementById(`base-value-${projectId}`).value,
        setup_script: document.getElementById(`setup-${projectId}`).value,
        default_ro_mounts: defaultMounts.ro_mounts,
        default_rw_mounts: defaultMounts.rw_mounts,
        default_env_vars: defaultEnv,
      };
      await fetchJson(`/api/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      uiDirty = false;
      await refresh();
    }

    async function createChatForProject(projectId) {
      let mountPayload;
      let envPayload;
      try {
        mountPayload = collectMountPayload(`new-volumes-${projectId}`);
        envPayload = collectEnvPayload(`new-env-${projectId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        project_id: projectId,
        profile: document.getElementById(`profile-${projectId}`).value,
        ro_mounts: mountPayload.ro_mounts,
        rw_mounts: mountPayload.rw_mounts,
        env_vars: envPayload,
      };
      await fetchJson('/api/chats', { method: 'POST', body: JSON.stringify(payload) });
      await saveProjectSettings(projectId);
      uiDirty = false;
      await refresh();
    }

    async function startChat(chatId) {
      await fetchJson(`/api/chats/${chatId}/start`, { method: 'POST' });
      await refresh();
    }

    async function closeChat(chatId) {
      await fetchJson(`/api/chats/${chatId}/close`, { method: 'POST' });
      await refresh();
    }

    async function deleteChat(chatId) {
      await fetchJson(`/api/chats/${chatId}`, { method: 'DELETE' });
      await refresh();
    }

    async function deleteProject(projectId) {
      if (!confirm('Delete this project and all chats? This removes stored clones.')) return;
      await fetchJson(`/api/projects/${projectId}`, { method: 'DELETE' });
      await refresh();
    }

    async function updateChat(chatId) {
      let mountPayload;
      let envPayload;
      try {
        mountPayload = collectMountPayload(`chat-volumes-${chatId}`);
        envPayload = collectEnvPayload(`chat-env-${chatId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        profile: document.getElementById(`chat-profile-${chatId}`).value,
        ro_mounts: mountPayload.ro_mounts,
        rw_mounts: mountPayload.rw_mounts,
        env_vars: envPayload,
      };
      await fetchJson(`/api/chats/${chatId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      uiDirty = false;
      await refresh();
    }

    async function viewLog(chatId) {
      const el = document.getElementById(`log-${chatId}`);
      const text = await fetchText(`/api/chats/${chatId}/logs`);
      el.textContent = text || '';
    }

    updateBasePlaceholderForCreate();
    seedVolumeRows('project-default-volumes', [], []);
    seedEnvRows('project-default-env', []);
    refresh();
    setInterval(refresh, 4000);
  </script>
</body>
</html>
    """


@click.command(help="Run the local Codex hub.")
@click.option("--data-dir", default=str(_default_data_dir()), show_default=True, type=click.Path(file_okay=False, path_type=Path), help="Directory for hub state and chat workspaces.")
@click.option("--config-file", default=str(_default_config_file()), show_default=True, type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Codex config file to pass into every chat.")
@click.option("--host", default=DEFAULT_HOST, show_default=True)
@click.option("--port", default=DEFAULT_PORT, show_default=True, type=int)
@click.option("--frontend-build/--no-frontend-build", default=True, show_default=True, help="Automatically build the React frontend before starting the server.")
@click.option("--clean-start", is_flag=True, default=False, help="Clear hub chat artifacts and cached setup images before serving.")
@click.option("--reload", is_flag=True, default=False)
def main(
    data_dir: Path,
    config_file: Path,
    host: str,
    port: int,
    frontend_build: bool,
    clean_start: bool,
    reload: bool,
) -> None:
    if _default_config_file() and not Path(config_file).exists():
        raise click.ClickException(f"Missing config file: {config_file}")
    if frontend_build:
        _ensure_frontend_built(data_dir)

    state = HubState(data_dir=data_dir, config_file=config_file)
    if clean_start:
        summary = state.clean_start()
        click.echo(
            "Clean start completed: "
            f"stopped_chats={summary['stopped_chats']} "
            f"cleared_chats={summary['cleared_chats']} "
            f"projects_reset={summary['projects_reset']} "
            f"docker_images_requested={summary['docker_images_requested']}"
        )

    app = FastAPI()
    frontend_dist = _frontend_dist_dir()
    frontend_index = _frontend_index_file()

    @app.get("/", response_class=HTMLResponse)
    def index():
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return HTMLResponse(_frontend_not_built_page(), status_code=503)

    @app.get("/api/state")
    def api_state() -> dict[str, Any]:
        return state.state_payload()

    @app.post("/api/projects")
    async def api_create_project(request: Request) -> dict[str, Any]:
        payload = await request.json()
        repo_url = str(payload.get("repo_url", "")).strip()
        name = payload.get("name")
        if name is not None:
            name = str(name).strip() or None
        branch = payload.get("default_branch")
        setup_script = payload.get("setup_script")
        base_image_mode = _normalize_base_image_mode(payload.get("base_image_mode"))
        base_image_value = str(payload.get("base_image_value") or "").strip()
        default_ro_mounts = _parse_mounts(_empty_list(payload.get("default_ro_mounts")), "default read-only mount")
        default_rw_mounts = _parse_mounts(_empty_list(payload.get("default_rw_mounts")), "default read-write mount")
        default_env_vars = _parse_env_vars(_empty_list(payload.get("default_env_vars")))
        if setup_script is not None:
            setup_script = str(setup_script).strip()
        if isinstance(branch, str):
            branch = branch.strip() or None
        return {
            "project": state.add_project(
                repo_url=repo_url,
                name=name,
                default_branch=branch,
                setup_script=setup_script,
                base_image_mode=base_image_mode,
                base_image_value=base_image_value,
                default_ro_mounts=default_ro_mounts,
                default_rw_mounts=default_rw_mounts,
                default_env_vars=default_env_vars,
            )
        }

    @app.patch("/api/projects/{project_id}")
    async def api_update_project(project_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        update: dict[str, Any] = {}
        if "setup_script" in payload:
            script = payload.get("setup_script")
            update["setup_script"] = str(script).strip() if script is not None else ""
        if "name" in payload:
            name = payload.get("name")
            update["name"] = str(name).strip() if name is not None else ""
        if "default_branch" in payload:
            branch = payload.get("default_branch")
            update["default_branch"] = str(branch).strip() if branch is not None else ""
        if "base_image_mode" in payload:
            update["base_image_mode"] = _normalize_base_image_mode(payload.get("base_image_mode"))
        if "base_image_value" in payload:
            value = payload.get("base_image_value")
            update["base_image_value"] = str(value).strip() if value is not None else ""
        if "default_ro_mounts" in payload:
            update["default_ro_mounts"] = _parse_mounts(
                _empty_list(payload.get("default_ro_mounts")),
                "default read-only mount",
            )
        if "default_rw_mounts" in payload:
            update["default_rw_mounts"] = _parse_mounts(
                _empty_list(payload.get("default_rw_mounts")),
                "default read-write mount",
            )
        if "default_env_vars" in payload:
            update["default_env_vars"] = _parse_env_vars(_empty_list(payload.get("default_env_vars")))
        if not update:
            raise HTTPException(status_code=400, detail="No patch values provided.")
        return {"project": state.update_project(project_id, update)}

    @app.delete("/api/projects/{project_id}")
    def api_delete_project(project_id: str) -> None:
        state.delete_project(project_id)

    @app.get("/api/projects/{project_id}/build-logs", response_class=PlainTextResponse)
    def api_project_build_logs(project_id: str) -> str:
        project = state.project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        log_path = state.project_build_log(project_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    @app.post("/api/projects/{project_id}/chats/start")
    def api_start_new_chat_for_project(project_id: str) -> dict[str, Any]:
        return {"chat": state.create_and_start_chat(project_id)}

    @app.post("/api/chats")
    async def api_create_chat(request: Request) -> dict[str, Any]:
        payload = await request.json()
        project_id = str(payload.get("project_id", "")).strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")

        profile = payload.get("profile")
        if profile is not None:
            profile = str(profile).strip()

        ro_mounts = _parse_mounts(_empty_list(payload.get("ro_mounts")), "read-only mount")
        rw_mounts = _parse_mounts(_empty_list(payload.get("rw_mounts")), "read-write mount")
        env_vars = _parse_env_vars(_empty_list(payload.get("env_vars")))
        codex_args = payload.get("codex_args")
        if codex_args is None:
            codex_args = []
        if not isinstance(codex_args, list):
            raise HTTPException(status_code=400, detail="codex_args must be an array.")
        return {
            "chat": state.create_chat(
                project_id,
                profile,
                ro_mounts,
                rw_mounts,
                env_vars,
                codex_args=[str(arg) for arg in codex_args],
            )
        }

    @app.post("/api/chats/{chat_id}/start")
    def api_start_chat(chat_id: str) -> dict[str, Any]:
        return {"chat": state.start_chat(chat_id)}

    @app.post("/api/chats/{chat_id}/close")
    def api_close_chat(chat_id: str) -> dict[str, Any]:
        return {"chat": state.close_chat(chat_id)}

    @app.patch("/api/chats/{chat_id}")
    async def api_patch_chat(chat_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        update: dict[str, Any] = {}
        if "profile" in payload:
            update["profile"] = str(payload.get("profile") or "").strip()
        if "ro_mounts" in payload:
            update["ro_mounts"] = _parse_mounts(_empty_list(payload.get("ro_mounts")), "read-only mount")
        if "rw_mounts" in payload:
            update["rw_mounts"] = _parse_mounts(_empty_list(payload.get("rw_mounts")), "read-write mount")
        if "env_vars" in payload:
            update["env_vars"] = _parse_env_vars(_empty_list(payload.get("env_vars")))
        if "codex_args" in payload:
            args = payload.get("codex_args")
            if not isinstance(args, list):
                raise HTTPException(status_code=400, detail="codex_args must be an array.")
            update["codex_args"] = [str(arg) for arg in args]
        if not update:
            raise HTTPException(status_code=400, detail="No patch values provided.")
        return {"chat": state.update_chat(chat_id, update)}

    @app.delete("/api/chats/{chat_id}")
    def api_delete_chat(chat_id: str) -> None:
        state.delete_chat(chat_id)

    @app.get("/api/chats/{chat_id}/logs", response_class=PlainTextResponse)
    def api_chat_logs(chat_id: str) -> str:
        chat = state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        log_path = state.chat_log(chat_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    @app.websocket("/api/chats/{chat_id}/terminal")
    async def ws_chat_terminal(chat_id: str, websocket: WebSocket) -> None:
        chat = state.chat(chat_id)
        if chat is None:
            await websocket.close(code=4404)
            return

        try:
            listener, backlog = state.attach_terminal(chat_id)
        except HTTPException as exc:
            await websocket.close(code=4409, reason=str(exc.detail))
            return

        await websocket.accept()
        if backlog:
            await websocket.send_text(backlog)

        async def stream_output() -> None:
            while True:
                chunk = await asyncio.to_thread(listener.get)
                if chunk is None:
                    break
                await websocket.send_text(chunk)

        async def stream_input() -> None:
            while True:
                message = await websocket.receive_text()
                payload: Any = None
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    state.write_terminal_input(chat_id, message)
                    continue

                if isinstance(payload, dict):
                    message_type = str(payload.get("type") or "")
                    if message_type == "resize":
                        state.resize_terminal(chat_id, int(payload.get("cols") or 0), int(payload.get("rows") or 0))
                        continue
                    if message_type == "input":
                        state.write_terminal_input(chat_id, str(payload.get("data") or ""))
                        continue

                state.write_terminal_input(chat_id, message)

        sender = asyncio.create_task(stream_output())
        receiver = asyncio.create_task(stream_input())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            state.detach_terminal(chat_id, listener)
            if not sender.done():
                sender.cancel()
            if not receiver.done():
                receiver.cancel()

    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = frontend_dist / path
        if candidate.is_file():
            return FileResponse(candidate)
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return HTMLResponse(_frontend_not_built_page(), status_code=503)

    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
