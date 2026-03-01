#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import pwd
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def _configure_git_identity() -> None:
    git_user_name = os.environ.get("AGENT_HUB_GIT_USER_NAME", "").strip()
    git_user_email = os.environ.get("AGENT_HUB_GIT_USER_EMAIL", "").strip()
    if not git_user_name and not git_user_email:
        return
    if not git_user_name or not git_user_email:
        raise RuntimeError(
            "AGENT_HUB_GIT_USER_NAME and AGENT_HUB_GIT_USER_EMAIL must be set together."
        )

    _run(["git", "config", "--global", "user.name", git_user_name])
    _run(["git", "config", "--global", "user.email", git_user_email])


def _configure_git_auth_from_env() -> None:
    github_token = os.environ.get("GITHUB_TOKEN", "").strip() or os.environ.get("GH_TOKEN", "").strip()
    if not github_token:
        return

    host = os.environ.get("AGENT_HUB_GIT_CREDENTIAL_HOST", "").strip().lower() or "github.com"
    scheme = os.environ.get("AGENT_HUB_GIT_CREDENTIAL_SCHEME", "").strip().lower() or "https"
    if scheme not in {"http", "https"}:
        raise RuntimeError(f"Unsupported AGENT_HUB_GIT_CREDENTIAL_SCHEME: {scheme}")

    username = os.environ.get("GITHUB_ACTOR", "").strip() or "x-access-token"
    encoded_username = urllib.parse.quote(username, safe="")
    encoded_token = urllib.parse.quote(github_token, safe="")
    credential_file = Path("/tmp/agent_hub_git_credentials")
    credential_file.write_text(f"{scheme}://{encoded_username}:{encoded_token}@{host}\n", encoding="utf-8")
    os.chmod(credential_file, 0o600)

    host_name = host.rsplit(":", 1)[0] if ":" in host else host
    git_prefix = f"{scheme}://{host}/"
    _run(["git", "config", "--global", "credential.helper", f"store --file={str(credential_file)}"])
    _run(["git", "config", "--global", "--add", f"url.{git_prefix}.insteadOf", f"git@{host_name}:"])
    _run(["git", "config", "--global", "--add", f"url.{git_prefix}.insteadOf", f"ssh://git@{host_name}/"])


def _configure_git_safe_directory_for_project() -> None:
    raw_project_path = str(os.environ.get("CONTAINER_PROJECT_PATH") or "").strip()
    if raw_project_path:
        project_path = Path(raw_project_path)
    else:
        project_path = Path.cwd()
    normalized = str(project_path if project_path.is_absolute() else project_path.resolve())
    if not normalized:
        return
    _run(["git", "config", "--global", "--add", "safe.directory", normalized])


def _ensure_workspace_tmp(*, workspace_tmp: Path | None = None) -> None:
    target = workspace_tmp or Path("/workspace/tmp")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            "Workspace tmp bootstrap failed: "
            f"path={str(target)!r} unable to create directory ({exc})"
        ) from exc


def _set_umask() -> None:
    local_umask = os.environ.get("LOCAL_UMASK", "0022")
    if local_umask and len(local_umask) in (3, 4) and local_umask.isdigit():
        os.umask(int(local_umask, 8))


def _ensure_workspace_permissions() -> None:
    if os.getuid() == 0:
        # Avoid mutating host-mounted workspace permissions when entrypoint runs as root.
        return
    try:
        _run(["chmod", "-R", "g+rwx", "/workspace"], check=False)
    except Exception:
        pass


def _resolve_runtime_username(uid: int) -> str:
    local_user = os.environ.get("LOCAL_USER", "").strip()
    if local_user:
        return local_user
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError) as exc:
        raise RuntimeError(
            "Unable to resolve runtime username. Set LOCAL_USER to the host username "
            f"for uid={uid}."
        ) from exc


def _ensure_user_in_passwd(*, username: str) -> None:
    uid = os.getuid()
    gid = os.getgid()
    if uid == 0:
        return

    passwd_path = Path("/etc/passwd")
    shadow_path = Path("/etc/shadow")

    try:
        passwd_lines = passwd_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        passwd_lines = []

    entry_for_uid = ""
    matched_username = False
    updated_lines: list[str] = []
    for line in passwd_lines:
        parts = line.split(":")
        if len(parts) < 7:
            updated_lines.append(line)
            continue
        if parts[0] == username and parts[2] == str(uid):
            matched_username = True
            parts[3] = str(gid)
            parts[4] = "Mapped Runtime User"
            parts[5] = "/workspace"
            parts[6] = "/bin/bash"
            updated_lines.append(":".join(parts))
            continue
        if parts[2] == str(uid):
            entry_for_uid = line
            parts[0] = username
            parts[3] = str(gid)
            parts[4] = "Mapped Runtime User"
            parts[5] = "/workspace"
            parts[6] = "/bin/bash"
            updated_lines.append(":".join(parts))
            matched_username = True
            continue
        updated_lines.append(line)

    if not matched_username:
        if entry_for_uid:
            return
        updated_lines.append(f"{username}:x:{uid}:{gid}:Mapped Runtime User:/workspace:/bin/bash")

    new_passwd = "\n".join(updated_lines).rstrip("\n") + "\n"
    try:
        passwd_path.write_text(new_passwd, encoding="utf-8")
    except OSError:
        return


def _parse_non_negative_int(raw_value: str) -> int | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        parsed = int(value, 10)
    except ValueError:
        return None
    if parsed < 0:
        return None
    return parsed


def _parse_gid_csv(raw_value: str) -> list[int]:
    gids: list[int] = []
    seen: set[int] = set()
    for token in str(raw_value or "").split(","):
        parsed = _parse_non_negative_int(token)
        if parsed is None or parsed in seen:
            continue
        gids.append(parsed)
        seen.add(parsed)
    return gids


def _resolve_runtime_uid_gid() -> tuple[int, int, list[int]] | None:
    explicit_uid = _parse_non_negative_int(str(os.environ.get("LOCAL_UID") or ""))
    explicit_gid = _parse_non_negative_int(str(os.environ.get("LOCAL_GID") or ""))
    if explicit_uid is not None and explicit_gid is not None:
        explicit_supp_gids = [
            gid
            for gid in _parse_gid_csv(str(os.environ.get("LOCAL_SUPPLEMENTARY_GIDS") or ""))
            if gid != explicit_gid
        ]
        return explicit_uid, explicit_gid, explicit_supp_gids

    candidates: list[Path] = []
    project_path = str(os.environ.get("CONTAINER_PROJECT_PATH") or "").strip()
    if project_path:
        candidates.append(Path(project_path))
    candidates.append(Path("/workspace"))

    for candidate in candidates:
        try:
            metadata = candidate.stat()
        except OSError:
            continue
        return int(metadata.st_uid), int(metadata.st_gid), []
    return None


def _ensure_workspace_root_ownership(*, uid: int, gid: int) -> None:
    if os.getuid() != 0:
        return
    targets: list[Path] = [Path("/workspace")]
    project_path = str(os.environ.get("CONTAINER_PROJECT_PATH") or "").strip()
    if project_path:
        targets.append(Path(project_path))

    for target in targets:
        try:
            metadata = target.stat()
        except OSError:
            continue
        if int(metadata.st_uid) == uid and int(metadata.st_gid) == gid:
            continue
        try:
            os.chown(target, uid, gid)
        except OSError as exc:
            raise RuntimeError(
                f"Workspace ownership bootstrap failed: path={str(target)!r} target_uid_gid={uid}:{gid} error={exc}"
            ) from exc


def _drop_privileges_to_runtime_identity() -> None:
    if os.getuid() != 0:
        return
    target = _resolve_runtime_uid_gid()
    if target is None:
        return
    uid, gid, supp_gids = target
    if uid == 0 and gid == 0:
        return
    _ensure_workspace_root_ownership(uid=uid, gid=gid)
    try:
        os.setgroups(supp_gids)
    except (PermissionError, OSError):
        pass
    os.setgid(gid)
    os.setuid(uid)

    try:
        shadow_lines = shadow_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        shadow_lines = []
    else:
        if shadow_lines:
            updated_shadow: list[str] = []
            saw_shadow_user = False
            for line in shadow_lines:
                parts = line.split(":")
                if parts and parts[0] == username:
                    if len(parts) < 9:
                        parts.extend([""] * (9 - len(parts)))
                    parts[1] = parts[1] or ""
                    updated_shadow.append(":".join(parts))
                    saw_shadow_user = True
                else:
                    updated_shadow.append(line)
            if not saw_shadow_user:
                updated_shadow.append(f"{username}::19888:0:99999:7:::")
            try:
                shadow_path.write_text("\n".join(updated_shadow).rstrip("\n") + "\n", encoding="utf-8")
            except OSError:
                pass


def _ensure_claude_native_command_path(*, command: list[str], home: str, source_path: Path | None = None) -> None:
    if not command:
        return
    if Path(command[0]).name != "claude":
        return

    resolved_source_path = source_path or Path("/usr/local/bin/claude")
    target_path = Path(home) / ".local" / "bin" / "claude"
    if target_path.exists() or target_path.is_symlink():
        if target_path.is_file() and os.access(target_path, os.X_OK):
            return
        raise RuntimeError(
            "Claude native bootstrap failed: "
            f"command={command!r} home={home!r} target={str(target_path)!r} "
            "target exists but is not an executable file."
        )

    if not resolved_source_path.is_file() or not os.access(resolved_source_path, os.X_OK):
        raise RuntimeError(
            "Claude native bootstrap failed: "
            f"command={command!r} home={home!r} source={str(resolved_source_path)!r} "
            "source command is missing or not executable."
        )

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.symlink_to(resolved_source_path)
    except OSError as exc:
        raise RuntimeError(
            "Claude native bootstrap failed: "
            f"command={command!r} home={home!r} source={str(resolved_source_path)!r} target={str(target_path)!r} "
            f"symlink creation error={exc}"
        ) from exc


def _ensure_claude_json_file(path: Path) -> None:
    try:
        if path.exists():
            if not path.is_file():
                raise RuntimeError(
                    "Claude config bootstrap failed: "
                    f"path={str(path)!r} is not a regular file."
                )
            raw = path.read_text(encoding="utf-8")
            try:
                json.loads(raw)
                return
            except json.JSONDecodeError:
                path.write_text("{}\n", encoding="utf-8")
                return

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            "Claude config bootstrap failed: "
            f"path={str(path)!r} unable to initialize config: {exc}"
        ) from exc
    except UnicodeError:
        path.write_text("{}\n", encoding="utf-8")


def _ack_runtime_ready() -> None:
    base_url = str(os.environ.get("AGENT_HUB_AGENT_TOOLS_URL") or "").strip().rstrip("/")
    token = str(os.environ.get("AGENT_HUB_AGENT_TOOLS_TOKEN") or "").strip()
    guid = str(os.environ.get("AGENT_HUB_READY_ACK_GUID") or "").strip()
    if not base_url or not token or not guid:
        return
    payload = {
        "guid": guid,
        "stage": "container_bootstrapped",
        "meta": {
            "entrypoint": "docker/agent_cli/docker-entrypoint.py",
            "pid": os.getpid(),
        },
    }
    request = urllib.request.Request(
        f"{base_url}/ack",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "x-agent-hub-agent-tools-token": token,
        },
        data=json.dumps(payload).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(request, timeout=5.0):
            return
    except (urllib.error.URLError, TimeoutError):
        return


def _entrypoint_main() -> None:
    command = list(sys.argv[1:]) if sys.argv[1:] else ["codex"]
    runtime_username = _resolve_runtime_username(os.getuid())
    local_home = os.environ.get("LOCAL_HOME", "").strip() or os.environ.get("HOME", "").strip() or "/tmp"
    if not os.environ.get("HOME"):
        os.environ["HOME"] = local_home
    os.environ["USER"] = runtime_username
    os.environ["LOGNAME"] = runtime_username

    if command and Path(command[0]).name == "claude":
        _ensure_claude_json_file(Path(os.environ["HOME"]) / ".claude.json")

    _drop_privileges_to_runtime_identity()
    _ensure_workspace_tmp()
    _set_umask()
    _ensure_user_in_passwd(username=runtime_username)
    _ensure_workspace_permissions()
    _ensure_claude_native_command_path(command=command, home=os.environ["HOME"])
    _configure_git_auth_from_env()
    _configure_git_identity()
    _configure_git_safe_directory_for_project()
    _ack_runtime_ready()

    os.execvp(command[0], command)


if __name__ == "__main__":
    _entrypoint_main()
