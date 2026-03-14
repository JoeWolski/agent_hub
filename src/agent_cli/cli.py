from __future__ import annotations

import json
import os
import pwd
import posixpath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import Any, Iterable, Iterator, Tuple

import click

from agent_cli import providers as agent_providers
from agent_cli.services import BuildService, LaunchPipelineDeps, LaunchPipelineInput, execute_launch_pipeline
from agent_core import (
    AgentRuntimeConfig,
    ConfigError,
    DEFAULT_RUNTIME_RUN_MODE,
    IdentityError,
    RUNTIME_RUN_MODE_AUTO,
    RUNTIME_RUN_MODE_CHOICES,
    RUNTIME_RUN_MODE_DOCKER,
    RUNTIME_RUN_MODE_NATIVE,
    load_agent_runtime_config,
)
from agent_core.errors import MountVisibilityError
from agent_core import build_inputs as core_build_inputs
from agent_core import identity as core_identity
from agent_core import launch as core_launch
from agent_core import paths as core_paths
from agent_core import runtime_images as core_runtime_images
from agent_core.config import RuntimeConfig
from agent_core import shared as core_shared


DEFAULT_AGENT_CLI_BASE_DOCKERFILE = "docker/agent_cli/Dockerfile.base"
AGENT_CLI_BASE_IMAGE = "agent-cli-base"
DEFAULT_BASE_IMAGE = AGENT_CLI_BASE_IMAGE
DEFAULT_SETUP_RUNTIME_IMAGE = "agent-ubuntu2204-setup:latest"
DEFAULT_RUNTIME_IMAGE = "agent-ubuntu2204-codex:latest"
CLAUDE_RUNTIME_IMAGE = "agent-ubuntu2204-claude:latest"
GEMINI_RUNTIME_IMAGE = "agent-ubuntu2204-gemini:latest"
DEFAULT_DOCKERFILE = "docker/agent_cli/Dockerfile"
DEFAULT_AGENT_COMMAND = "codex"
DEFAULT_CONTAINER_HOME = "/workspace"
AGENT_PROVIDER_NONE = "none"
AGENT_PROVIDER_CODEX = "codex"
AGENT_PROVIDER_CLAUDE = "claude"
AGENT_PROVIDER_GEMINI = "gemini"
DEFAULT_CODEX_APPROVAL_POLICY = "never"
DEFAULT_CODEX_SANDBOX_MODE = "danger-full-access"
DEFAULT_CLAUDE_PERMISSION_MODE = "bypassPermissions"
DEFAULT_CLAUDE_MODEL = "opus"
DEFAULT_GEMINI_APPROVAL_MODE = "yolo"
GEMINI_CONTEXT_FILE_NAME = "GEMINI.md"
GEMINI_SETTINGS_FILE_NAME = "settings.json"
SYSTEM_PROMPT_FILE_NAME = "SYSTEM_PROMPT.md"
DOCKER_SOCKET_PATH = "/var/run/docker.sock"
TMP_DIR_TMPFS_SPEC = "/tmp:mode=1777,exec"
DEFAULT_RUNTIME_TERM = "xterm-256color"
DEFAULT_RUNTIME_COLORTERM = "truecolor"
SNAPSHOT_SOURCE_PROJECT_PATH = str(
    PurePosixPath(DEFAULT_CONTAINER_HOME) / ".agent-hub-snapshot-source" / "project"
)
GIT_CREDENTIALS_SOURCE_PATH = "/workspace/tmp/agent_hub_git_credentials_source"
GIT_CREDENTIALS_FILE_PATH = "/workspace/tmp/agent_hub_git_credentials"
AGENT_HUB_SECRETS_DIR_NAME = "secrets"
AGENT_HUB_GIT_CREDENTIALS_DIR_NAME = "git_credentials"
AGENT_HUB_DATA_DIR_ENV = "AGENT_HUB_DATA_DIR"
AGENT_TOOLS_URL_ENV = "AGENT_HUB_AGENT_TOOLS_URL"
AGENT_TOOLS_TOKEN_ENV = "AGENT_HUB_AGENT_TOOLS_TOKEN"
AGENT_TOOLS_PROJECT_ID_ENV = "AGENT_HUB_AGENT_TOOLS_PROJECT_ID"
AGENT_TOOLS_CHAT_ID_ENV = "AGENT_HUB_AGENT_TOOLS_CHAT_ID"
AGENT_TOOLS_READY_ACK_GUID_ENV = "AGENT_HUB_READY_ACK_GUID"
AGENT_HUB_TMP_HOST_PATH_ENV = "AGENT_HUB_TMP_HOST_PATH"
AGENT_TOOLS_TOKEN_HEADER = "x-agent-hub-agent-tools-token"
AGENT_TOOLS_MCP_RUNTIME_DIR_NAME = "agent_hub"
AGENT_TOOLS_MCP_RUNTIME_FILE_NAME = "agent_tools_mcp.py"
AGENT_TOOLS_MCP_CONTAINER_SCRIPT_PATH = str(
    PurePosixPath(DEFAULT_CONTAINER_HOME)
    / ".codex"
    / AGENT_TOOLS_MCP_RUNTIME_DIR_NAME
    / AGENT_TOOLS_MCP_RUNTIME_FILE_NAME
)
CODEX_RUNTIME_HOME_CONTAINER_PATH = str(PurePosixPath(DEFAULT_CONTAINER_HOME) / ".codex-runtime")
GIT_CREDENTIAL_DEFAULT_SCHEME = "https"
GIT_CREDENTIAL_ALLOWED_SCHEMES = {"http", "https"}
RUNTIME_IMAGE_BUILD_LOCK_DIR = Path(tempfile.gettempdir()) / "agent-cli-image-build-locks"
DAEMON_TMP_MOUNT_ROOT = Path("/workspace/tmp")


def _cli_arg_matches_option(arg: str, *, long_option: str, short_option: str | None = None) -> bool:
    if arg == long_option or arg.startswith(f"{long_option}="):
        return True
    if short_option and (arg == short_option or arg.startswith(f"{short_option}=")):
        return True
    return False


def _has_codex_config_override(args: Iterable[str], *, key: str) -> bool:
    parsed_args = [str(arg) for arg in args]
    for index, arg in enumerate(parsed_args):
        if not _cli_arg_matches_option(arg, long_option="--config", short_option="-c"):
            continue
        if arg in {"--config", "-c"}:
            if index + 1 >= len(parsed_args):
                continue
            config_assignment = parsed_args[index + 1]
        else:
            _, _, config_assignment = arg.partition("=")
        config_key, _, _ = config_assignment.partition("=")
        if config_key.strip() == key:
            return True
    return False


def _resolved_runtime_term(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    candidate = str(source.get("TERM", "")).strip()
    if not candidate or candidate.lower() == "dumb":
        return DEFAULT_RUNTIME_TERM
    return candidate


def _resolved_runtime_colorterm(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    candidate = str(source.get("COLORTERM", "")).strip()
    if not candidate:
        return DEFAULT_RUNTIME_COLORTERM
    return candidate


def _runtime_identity_from_config(runtime_config: AgentRuntimeConfig) -> tuple[int | None, int | None, str, str]:
    identity_config = core_identity.parse_runtime_identity_config(runtime_config)
    configured_uid, configured_gid = core_identity.parse_configured_uid_gid(
        identity_config,
        error_factory=lambda message: IdentityError(message),
    )
    return configured_uid, configured_gid, identity_config.username, identity_config.supplementary_gids


def _toml_basic_string_literal(value: str) -> str:
    return json.dumps(str(value or ""))


def _normalize_string_list(raw_value: object) -> list[str]:
    if not isinstance(raw_value, list):
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_value:
        value = str(item).strip()
        if not value or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    return cleaned


def _read_system_prompt(system_prompt_path: Path) -> str:
    try:
        return system_prompt_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise click.ClickException(f"Unable to read system prompt file {system_prompt_path}: {exc}") from exc


def _shared_prompt_context_from_runtime_config(
    runtime_config: AgentRuntimeConfig, *, core_system_prompt: str
) -> str:
    sections: list[str] = []
    if core_system_prompt:
        sections.append(core_system_prompt)

    parsed: dict[str, Any] = {}
    if isinstance(runtime_config.runtime.values, dict):
        parsed.update(runtime_config.runtime.values)

    project_doc_auto_load = parsed.get("project_doc_auto_load") is True
    doc_fallback_files = _normalize_string_list(parsed.get("project_doc_fallback_filenames"))
    doc_extra_files = _normalize_string_list(parsed.get("project_doc_auto_load_extra_filenames"))
    project_doc_max_bytes = parsed.get("project_doc_max_bytes")

    project_doc_files = _normalize_string_list(doc_fallback_files + doc_extra_files)
    if project_doc_auto_load and project_doc_files:
        doc_lines = "\n".join(f"- {name}" for name in project_doc_files)
        doc_section = (
            "Before you start coding, read these repository files if they exist and treat them as authoritative context:\n"
            f"{doc_lines}"
        )
        if isinstance(project_doc_max_bytes, int) and project_doc_max_bytes > 0:
            doc_section += f"\nLimit each file read to about {project_doc_max_bytes} bytes."
        sections.append(doc_section)

    return "\n\n".join(section for section in sections if section)


def _sync_gemini_shared_context_file(*, host_gemini_dir: Path, shared_prompt_context: str) -> None:
    context_file = host_gemini_dir / GEMINI_CONTEXT_FILE_NAME
    updated_context = str(shared_prompt_context or "").strip()
    updated = f"{updated_context}\n" if updated_context else ""

    existing = ""
    if context_file.exists():
        try:
            existing = context_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            click.echo(f"Warning: unable to read Gemini context file {context_file}: {exc}", err=True)
            return

    if existing == updated:
        return

    try:
        if updated:
            context_file.parent.mkdir(parents=True, exist_ok=True)
            context_file.write_text(updated, encoding="utf-8")
        elif context_file.exists():
            context_file.unlink()
    except OSError as exc:
        click.echo(f"Warning: unable to update Gemini context file {context_file}: {exc}", err=True)


def _repo_root() -> Path:
    return core_shared.repo_root(Path(__file__))


def _default_config_file() -> Path:
    return core_shared.default_config_file(_repo_root(), cwd=Path.cwd())


def _default_system_prompt_file() -> Path:
    return core_shared.default_system_prompt_file(_repo_root(), SYSTEM_PROMPT_FILE_NAME, cwd=Path.cwd())


def _default_credentials_file() -> Path:
    return _repo_root() / ".credentials"


def _default_agent_hub_data_dir() -> Path:
    return core_paths.default_agent_hub_data_dir()


def _default_agent_hub_git_credentials_dir() -> Path:
    return _default_agent_hub_data_dir() / AGENT_HUB_SECRETS_DIR_NAME / AGENT_HUB_GIT_CREDENTIALS_DIR_NAME


def _split_host_port(host: str) -> tuple[str, int | None]:
    return core_shared.split_host_port(
        host,
        error_factory=lambda message: click.ClickException(message),
    )


def _normalize_git_credential_scheme(raw_value: str) -> str:
    scheme = str(raw_value or "").strip().lower()
    if not scheme:
        return GIT_CREDENTIAL_DEFAULT_SCHEME
    if scheme not in GIT_CREDENTIAL_ALLOWED_SCHEMES:
        raise click.ClickException(f"Invalid git credential scheme: {raw_value}")
    return scheme


def _parse_git_credential_store_host(credential_line: str) -> tuple[str, str] | None:
    candidate = str(credential_line or "").strip()
    if not candidate:
        return None
    try:
        parsed = urllib.parse.urlsplit(candidate)
    except ValueError:
        return None
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return None
    scheme = _normalize_git_credential_scheme(parsed.scheme)
    if parsed.port:
        host = f"{host}:{parsed.port}"
    try:
        return _normalize_git_credential_host(host), scheme
    except click.ClickException:
        return None


def _discover_agent_hub_git_credentials() -> tuple[Path | None, str, str]:
    credentials_dir = _default_agent_hub_git_credentials_dir()
    if not credentials_dir.is_dir():
        return None, "", ""

    candidates: list[Path] = []
    try:
        for path in credentials_dir.iterdir():
            if not path.is_file():
                continue
            candidates.append(path)
    except OSError:
        return None, "", ""
    if not candidates:
        return None, "", ""

    def _sort_key(path: Path) -> tuple[float, str]:
        try:
            mtime = float(path.stat().st_mtime)
        except OSError:
            mtime = 0.0
        return (mtime, path.name)

    candidates.sort(key=_sort_key, reverse=True)
    for credentials_path in candidates:
        try:
            with credentials_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    parsed = _parse_git_credential_store_host(line)
                    if parsed is None:
                        continue
                    host, scheme = parsed
                    return credentials_path.resolve(), host, scheme
        except (OSError, UnicodeError):
            continue
    return None, "", ""


def _resolved_agent_hub_data_dir(runtime_config: AgentRuntimeConfig | None = None) -> Path:
    if runtime_config is not None and isinstance(runtime_config.paths.values, dict):
        return core_paths.resolve_agent_hub_data_dir(runtime_config.paths.values)
    return core_paths.default_agent_hub_data_dir()


def _write_private_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _materialize_codex_runtime_home(*, host_codex_dir: Path, runtime_config_path: Path) -> Path:
    runtime_home_root = host_codex_dir.parent / ".codex-runtime-homes"
    runtime_home_path = runtime_home_root / uuid.uuid4().hex
    try:
        if host_codex_dir.exists():
            shutil.copytree(host_codex_dir, runtime_home_path, symlinks=True)
        else:
            runtime_home_path.mkdir(parents=True, exist_ok=True)
        runtime_config_text = runtime_config_path.read_text(encoding="utf-8")
        _write_private_text_file(runtime_home_path / "config.toml", runtime_config_text)
    except OSError as exc:
        raise click.ClickException(f"Failed to materialize Codex runtime home {runtime_home_path}: {exc}") from exc
    return runtime_home_path


def _strip_mcp_server_table(config_text: str, server_name: str) -> str:
    if not config_text:
        return ""
    escaped_name = re.escape(server_name)
    pattern = re.compile(r"(?ms)^\[mcp_servers\." + escaped_name + r"(?:\.[^\]]+)?\]\n.*?(?=^\[|\Z)")
    stripped = re.sub(pattern, "", config_text)
    return stripped.rstrip() + "\n"


def _env_var_keys(entries: Iterable[str]) -> set[str]:
    keys: set[str] = set()
    for entry in entries:
        key, _sep, _value = str(entry).partition("=")
        normalized = key.strip()
        if normalized:
            keys.add(normalized)
    return keys


def _agent_tools_env_from_entries(entries: Iterable[str]) -> dict[str, str]:
    env_values: dict[str, str] = {}
    for entry in entries:
        key, sep, value = str(entry).partition("=")
        normalized_key = key.strip()
        if not normalized_key or not sep:
            continue
        if normalized_key in {
            AGENT_TOOLS_URL_ENV,
            AGENT_TOOLS_TOKEN_ENV,
            AGENT_TOOLS_PROJECT_ID_ENV,
            AGENT_TOOLS_CHAT_ID_ENV,
            AGENT_TOOLS_READY_ACK_GUID_ENV,
        }:
            env_values[normalized_key] = value.strip()

    return {
        AGENT_TOOLS_URL_ENV: env_values.get(AGENT_TOOLS_URL_ENV, ""),
        AGENT_TOOLS_TOKEN_ENV: env_values.get(AGENT_TOOLS_TOKEN_ENV, ""),
        AGENT_TOOLS_PROJECT_ID_ENV: env_values.get(AGENT_TOOLS_PROJECT_ID_ENV, ""),
        AGENT_TOOLS_CHAT_ID_ENV: env_values.get(AGENT_TOOLS_CHAT_ID_ENV, ""),
        AGENT_TOOLS_READY_ACK_GUID_ENV: env_values.get(AGENT_TOOLS_READY_ACK_GUID_ENV, ""),
    }


def _git_origin_repo_url(project_path: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(project_path), "remote", "get-url", "origin"],
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return ""
    return str(result.stdout or "").strip()


@dataclass
class _AgentToolsRuntimeBridge:
    runtime_config_path: Path
    env_vars: list[str]
    state: object | None
    session_id: str
    server: ThreadingHTTPServer | None
    thread: Thread | None
    mounts: list[str] = field(default_factory=list)
    mount_runtime_config: bool = True
    cleanup_runtime_config: bool = True
    runtime_codex_home_path: Path | None = None

    def close(self) -> None:
        if self.server is not None:
            try:
                self.server.shutdown()
            except Exception:
                pass
            try:
                self.server.server_close()
            except Exception:
                pass
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2.0)

        remove_session = getattr(self.state, "remove_agent_tools_session", None) if self.state is not None else None
        if self.session_id and callable(remove_session):
            try:
                remove_session(self.session_id)
            except Exception:
                pass
        if self.cleanup_runtime_config:
            try:
                self.runtime_config_path.unlink(missing_ok=True)
            except OSError:
                pass
        if self.runtime_codex_home_path is not None:
            try:
                shutil.rmtree(self.runtime_codex_home_path)
            except OSError:
                pass


def _resolve_existing_project_context(state: object, repo_url: str) -> tuple[str, dict[str, object]]:
    from agent_hub import server as hub_server

    target_repo = str(repo_url or "").strip()
    if not target_repo:
        return "", hub_server.normalize_project_credential_binding(None)

    target_host = hub_server.git_repo_host(target_repo)
    target_owner = hub_server.git_repo_owner(target_repo)
    target_name = hub_server.extract_repo_name(target_repo).lower().strip()
    if not target_host or not target_name:
        return "", hub_server.normalize_project_credential_binding(None)

    state_payload = state.load()
    projects = state_payload.get("projects")
    if not isinstance(projects, dict):
        return "", hub_server.normalize_project_credential_binding(None)

    for project_id, project in projects.items():
        if not isinstance(project, dict):
            continue
        project_repo = str(project.get("repo_url") or "").strip()
        if not project_repo:
            continue
        host = hub_server.git_repo_host(project_repo)
        owner = hub_server.git_repo_owner(project_repo)
        name = hub_server.extract_repo_name(project_repo).lower().strip()
        if host == target_host and owner == target_owner and name == target_name:
            binding = hub_server.normalize_project_credential_binding(project.get("credential_binding"))
            return str(project_id), binding

    return "", hub_server.normalize_project_credential_binding(None)


def _build_agent_tools_runtime_config(
    *,
    config_path: Path,
    host_codex_dir: Path,
    agent_tools_env: dict[str, str],
    agent_provider: agent_providers.AgentProvider,
    container_home: str,
    agent_tools_config_path: Path | None = None,
) -> Path:
    from agent_hub import server as hub_server

    source_script = hub_server.agent_tools_mcp_source_path()
    try:
        script_text = source_script.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Failed to read agent_tools MCP script {source_script}: {exc}") from exc

    runtime_script = host_codex_dir / AGENT_TOOLS_MCP_RUNTIME_DIR_NAME / AGENT_TOOLS_MCP_RUNTIME_FILE_NAME
    if runtime_script.exists():
        try:
            existing_script = runtime_script.read_text(encoding="utf-8")
        except OSError:
            existing_script = ""
    else:
        existing_script = ""
    if existing_script != script_text:
        try:
            _write_private_text_file(runtime_script, script_text)
        except OSError as exc:
            raise click.ClickException(f"Failed to materialize agent_tools MCP script {runtime_script}: {exc}") from exc

    if isinstance(agent_provider, (agent_providers.ClaudeProvider, agent_providers.GeminiProvider)):
        base_config_path = agent_tools_config_path or config_path
        runtime_config_path = base_config_path if agent_tools_config_path is not None else (
            host_codex_dir / f"agent-tools-runtime-{uuid.uuid4().hex}.json"
        )
    else:
        base_config_path = config_path
        runtime_config_path = host_codex_dir / f"agent-tools-runtime-{uuid.uuid4().hex}.toml"

    try:
        base_config = base_config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Failed to read config file {base_config_path}: {exc}") from exc

    if (
        isinstance(agent_provider, (agent_providers.ClaudeProvider, agent_providers.GeminiProvider))
        and agent_tools_config_path is not None
    ):
        base_config_text = base_config.strip()
        if base_config_text:
            try:
                parsed_config = json.loads(base_config_text)
            except json.JSONDecodeError as exc:
                raise click.ClickException(
                    f"Failed to parse JSON config file {base_config_path}: {exc}"
                ) from exc
            if not isinstance(parsed_config, dict):
                raise click.ClickException(f"{base_config_path} must contain a JSON object for MCP config merging.")

    agent_tools_url = str(agent_tools_env.get(AGENT_TOOLS_URL_ENV) or "").strip()
    agent_tools_token = str(agent_tools_env.get(AGENT_TOOLS_TOKEN_ENV) or "").strip()
    if not agent_tools_url:
        raise click.ClickException(f"Missing required {AGENT_TOOLS_URL_ENV} for agent_tools MCP runtime config.")
    if not agent_tools_token:
        raise click.ClickException(f"Missing required {AGENT_TOOLS_TOKEN_ENV} for agent_tools MCP runtime config.")

    normalized_container_home = str(container_home or "").strip() or DEFAULT_CONTAINER_HOME
    mcp_script_path = str(
        PurePosixPath(normalized_container_home)
        / ".codex"
        / AGENT_TOOLS_MCP_RUNTIME_DIR_NAME
        / AGENT_TOOLS_MCP_RUNTIME_FILE_NAME
    )

    merged_config = agent_provider.build_mcp_config(
        base_config_text=base_config,
        mcp_env={
            AGENT_TOOLS_URL_ENV: agent_tools_url,
            AGENT_TOOLS_TOKEN_ENV: agent_tools_token,
            AGENT_TOOLS_PROJECT_ID_ENV: str(agent_tools_env.get(AGENT_TOOLS_PROJECT_ID_ENV) or '').strip(),
            AGENT_TOOLS_CHAT_ID_ENV: str(agent_tools_env.get(AGENT_TOOLS_CHAT_ID_ENV) or '').strip(),
        },
        script_path=mcp_script_path,
    )

    ext = ".json" if isinstance(agent_provider, (agent_providers.ClaudeProvider, agent_providers.GeminiProvider)) else ".toml"
    if runtime_config_path.suffix != ext:
        runtime_config_path = runtime_config_path.with_suffix(ext)

    try:
        _write_private_text_file(runtime_config_path, merged_config)
    except OSError as exc:
        raise click.ClickException(f"Failed to write runtime config {runtime_config_path}: {exc}") from exc
    return runtime_config_path


def _start_agent_tools_runtime_bridge(
    *,
    project_path: Path,
    host_codex_dir: Path,
    config_path: Path,
    system_prompt_path: Path,
    agent_tools_config_path: Path | None,
    parsed_env_vars: list[str],
    agent_provider: agent_providers.AgentProvider,
    container_home: str,
    runtime_config: AgentRuntimeConfig,
    effective_run_mode: str,
) -> _AgentToolsRuntimeBridge | None:
    preserve_agent_tools_config = bool(
        isinstance(agent_provider, (agent_providers.ClaudeProvider, agent_providers.GeminiProvider))
        and agent_tools_config_path is not None
    )

    def _codex_runtime_home_overlay(runtime_config_path: Path) -> tuple[list[str], list[str], Path | None, bool]:
        if not isinstance(agent_provider, agent_providers.CodexProvider):
            return [], [], None, True
        runtime_codex_home_path = _materialize_codex_runtime_home(
            host_codex_dir=host_codex_dir,
            runtime_config_path=runtime_config_path,
        )
        _validate_daemon_visible_mount_source(runtime_codex_home_path, label="Codex runtime home")
        mapped_runtime_codex_home = _daemon_visible_mount_source(runtime_codex_home_path)
        if mapped_runtime_codex_home != runtime_codex_home_path:
            _validate_daemon_visible_mount_source(
                mapped_runtime_codex_home,
                label="Codex runtime home (mapped)",
            )
        return (
            [f"{mapped_runtime_codex_home}:{CODEX_RUNTIME_HOME_CONTAINER_PATH}"],
            [f"CODEX_HOME={CODEX_RUNTIME_HOME_CONTAINER_PATH}"],
            runtime_codex_home_path,
            False,
        )

    if AGENT_TOOLS_URL_ENV in _env_var_keys(parsed_env_vars) or AGENT_TOOLS_TOKEN_ENV in _env_var_keys(parsed_env_vars):
        keys = _env_var_keys(parsed_env_vars)
        if AGENT_TOOLS_URL_ENV not in keys or AGENT_TOOLS_TOKEN_ENV not in keys:
            raise click.ClickException(
                f"{AGENT_TOOLS_URL_ENV} and {AGENT_TOOLS_TOKEN_ENV} must be provided together when using --env-var."
            )
        runtime_config_path = _build_agent_tools_runtime_config(
            config_path=config_path,
            host_codex_dir=host_codex_dir,
            agent_tools_env=_agent_tools_env_from_entries(parsed_env_vars),
            agent_provider=agent_provider,
            container_home=container_home,
            agent_tools_config_path=agent_tools_config_path if isinstance(
                agent_provider,
                (agent_providers.ClaudeProvider, agent_providers.GeminiProvider),
            ) else None,
        )
        runtime_mounts, runtime_env_vars, runtime_codex_home_path, mount_runtime_config = _codex_runtime_home_overlay(
            runtime_config_path
        )
        return _AgentToolsRuntimeBridge(
            runtime_config_path=runtime_config_path,
            env_vars=runtime_env_vars,
            state=None,
            session_id="",
            server=None,
            thread=None,
            mounts=runtime_mounts,
            mount_runtime_config=mount_runtime_config,
            cleanup_runtime_config=not preserve_agent_tools_config,
            runtime_codex_home_path=runtime_codex_home_path,
        )

    from agent_hub import server as hub_server

    data_dir = _resolved_agent_hub_data_dir(runtime_config)
    bridge_runtime_config = runtime_config
    if effective_run_mode == RUNTIME_RUN_MODE_DOCKER and runtime_config.runtime.run_mode != RUNTIME_RUN_MODE_DOCKER:
        bridge_runtime_config = AgentRuntimeConfig(
            identity=runtime_config.identity,
            paths=runtime_config.paths,
            providers=runtime_config.providers,
            mcp=runtime_config.mcp,
            auth=runtime_config.auth,
            logging=runtime_config.logging,
            runtime=RuntimeConfig(
                run_mode=RUNTIME_RUN_MODE_DOCKER,
                strict_mode=bool(runtime_config.runtime.strict_mode),
                values=dict(runtime_config.runtime.values),
            ),
            extras=dict(runtime_config.extras),
        )

    hub_state_kwargs: dict[str, object] = {
        "data_dir": data_dir,
        "config_file": config_path,
        "runtime_config": bridge_runtime_config,
        "system_prompt_file": system_prompt_path,
        "artifact_publish_base_url": "http://127.0.0.1",
        "reconcile_project_build_on_init": False,
    }

    hub_state = hub_server.HubState(**hub_state_kwargs)
    repo_url = _git_origin_repo_url(project_path)
    project_id = ""
    session_id = ""
    runtime_config_path: Path | None = None
    server: ThreadingHTTPServer | None = None
    thread: Thread | None = None
    try:
        project_id, credential_binding = _resolve_existing_project_context(hub_state, repo_url)
        session_id, session_token = hub_state.create_agent_tools_session(
            project_id=project_id,
            repo_url=repo_url,
            credential_binding=credential_binding,
        )
        ready_ack_guid = hub_state.issue_agent_tools_session_ready_ack_guid(session_id)

        class _BridgeHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                del format, args
                return

            def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _read_payload(self) -> dict[str, object]:
                try:
                    content_length = int(str(self.headers.get("Content-Length") or "0"))
                except ValueError:
                    content_length = 0
                if content_length <= 0:
                    return {}
                body = self.rfile.read(content_length).decode("utf-8", errors="ignore")
                if not body.strip():
                    return {}
                try:
                    parsed = json.loads(body)
                except json.JSONDecodeError as exc:
                    raise click.ClickException(f"Invalid JSON payload: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise click.ClickException("Invalid JSON payload.")
                return parsed

            def _request_token(self) -> str:
                auth_header = str(self.headers.get("Authorization") or "")
                if auth_header.lower().startswith("bearer "):
                    return auth_header[7:].strip()
                return str(self.headers.get(AGENT_TOOLS_TOKEN_HEADER) or "").strip()

            def _authorize(self) -> None:
                hub_state.require_agent_tools_session_token(session_id, self._request_token())

            @staticmethod
            def _http_detail(exc: Exception) -> tuple[int, str]:
                status_code = int(getattr(exc, "status_code", 500))
                detail = str(getattr(exc, "detail", str(exc)))
                return status_code, detail

            def do_GET(self) -> None:  # noqa: N802
                path = urllib.parse.urlsplit(self.path).path
                if path != "/credentials":
                    self._send_json(404, {"detail": "Not found."})
                    return
                try:
                    self._authorize()
                    payload = hub_state.agent_tools_session_credentials_list_payload(session_id)
                except Exception as exc:
                    status_code, detail = self._http_detail(exc)
                    self._send_json(status_code, {"detail": detail})
                    return
                self._send_json(200, payload)

            def do_POST(self) -> None:  # noqa: N802
                path = urllib.parse.urlsplit(self.path).path
                if path not in {"/credentials/resolve", "/project-binding", "/artifacts/submit", "/ack"}:
                    self._send_json(404, {"detail": "Not found."})
                    return
                try:
                    self._authorize()
                    payload = self._read_payload()
                    if path == "/credentials/resolve":
                        mode = payload.get("mode")
                        credential_ids = payload.get("credential_ids")
                        response = hub_state.resolve_agent_tools_session_credentials(
                            session_id=session_id,
                            mode=mode,
                            credential_ids=credential_ids,
                        )
                    elif path == "/project-binding":
                        mode = payload.get("mode")
                        credential_ids = payload.get("credential_ids")
                        response = hub_state.attach_agent_tools_session_project_credentials(
                            session_id=session_id,
                            mode=mode,
                            credential_ids=credential_ids,
                        )
                    elif path == "/ack":
                        response = {
                            "ack": hub_state.acknowledge_agent_tools_session_ready(
                                session_id=session_id,
                                token=self._request_token(),
                                guid=payload.get("guid"),
                                stage=payload.get("stage"),
                                meta=payload.get("meta"),
                            )
                        }
                    else:
                        response = {
                            "artifact": hub_state.submit_session_artifact(
                                session_id=session_id,
                                token=self._request_token(),
                                submitted_path=payload.get("path"),
                                name=payload.get("name"),
                            )
                        }
                except Exception as exc:
                    status_code, detail = self._http_detail(exc)
                    self._send_json(status_code, {"detail": detail})
                    return
                self._send_json(200, response)

        server = ThreadingHTTPServer(("0.0.0.0", 0), _BridgeHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        bridge_port = int(server.server_address[1])
        env_vars = [
            f"{AGENT_TOOLS_URL_ENV}=http://host.docker.internal:{bridge_port}",
            f"{AGENT_TOOLS_TOKEN_ENV}={session_token}",
            f"{AGENT_TOOLS_PROJECT_ID_ENV}={project_id}",
            f"{AGENT_TOOLS_CHAT_ID_ENV}=agent_cli:{session_id}",
            f"{AGENT_TOOLS_READY_ACK_GUID_ENV}={ready_ack_guid}",
        ]
        runtime_config_path = _build_agent_tools_runtime_config(
            config_path=config_path,
            host_codex_dir=host_codex_dir,
            agent_tools_env=_agent_tools_env_from_entries(env_vars),
            agent_provider=agent_provider,
            container_home=container_home,
            agent_tools_config_path=agent_tools_config_path if isinstance(
                agent_provider,
                (agent_providers.ClaudeProvider, agent_providers.GeminiProvider),
            ) else None,
        )
        runtime_mounts, runtime_env_vars, runtime_codex_home_path, mount_runtime_config = _codex_runtime_home_overlay(
            runtime_config_path
        )
        return _AgentToolsRuntimeBridge(
            runtime_config_path=runtime_config_path,
            env_vars=[*env_vars, *runtime_env_vars],
            state=hub_state,
            session_id=session_id,
            server=server,
            thread=thread,
            mounts=runtime_mounts,
            mount_runtime_config=mount_runtime_config,
            cleanup_runtime_config=not preserve_agent_tools_config,
            runtime_codex_home_path=runtime_codex_home_path,
        )
    except Exception:
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        if session_id:
            remove_session = getattr(hub_state, "remove_agent_tools_session", None)
            if callable(remove_session):
                try:
                    remove_session(session_id)
                except Exception:
                    pass
        if runtime_config_path is not None:
            if not preserve_agent_tools_config:
                try:
                    runtime_config_path.unlink(missing_ok=True)
                except OSError:
                    pass
        raise


def _default_group_name() -> str:
    import grp

    return grp.getgrgid(os.getgid()).gr_name


def _gid_for_group_name(group_name: str) -> int:
    import grp

    normalized = str(group_name or "").strip()
    if not normalized:
        raise click.ClickException("Group name must not be empty")
    try:
        return int(grp.getgrnam(normalized).gr_gid)
    except KeyError as exc:
        raise click.ClickException(f"Unknown group name: {normalized}") from exc


def _default_supplementary_gids() -> str:
    return core_identity.default_supplementary_gids()


def _default_supplementary_groups() -> str:
    import grp

    groups: list[str] = []
    for gid in sorted({gid for gid in os.getgroups() if gid != os.getgid()}):
        try:
            groups.append(grp.getgrgid(gid).gr_name)
        except KeyError:
            groups.append(str(gid))
    return ",".join(groups)


def _to_absolute(value: str, cwd: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (cwd / path).resolve()


def _short_hash(value: str) -> str:
    return core_runtime_images.short_hash(value)


def _sanitize_tag_component(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9_.-]", "-", value.lower())
    sanitized = sanitized.strip("-")
    return sanitized or "base"


def _run(cmd: Iterable[str], cwd: Path | None = None) -> None:
    try:
        subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, check=True)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}")


def _docker_image_exists(tag: str) -> bool:
    return core_shared.docker_image_exists(tag)


def _docker_rm_force(container_name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", container_name],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _normalize_csv(value: str | None) -> str:
    return core_shared.normalize_csv(value)


def _parse_gid_csv(value: str) -> list[int]:
    return core_shared.parse_gid_csv(
        value,
        strict=True,
        error_factory=lambda message: click.ClickException(message),
    )


def _group_names_to_gid_csv(value: str | None) -> str:
    if value is None:
        return ""
    names = _normalize_csv(value)
    if not names:
        return ""
    gids = [str(_gid_for_group_name(name)) for name in names.split(",") if name]
    return _normalize_csv(",".join(gids))


def _docker_socket_gid() -> int | None:
    try:
        return int(os.stat(DOCKER_SOCKET_PATH).st_gid)
    except OSError:
        return None


def _parse_mount(spec: str, label: str) -> Tuple[str, str]:
    if ":" not in spec:
        raise click.ClickException(f"Invalid {label}: {spec} (expected /host/path:/container/path)")
    host, container = spec.split(":", 1)
    if not host or not container:
        raise click.ClickException(f"Invalid {label}: {spec} (expected /host/path:/container/path)")
    if not container.startswith("/"):
        raise click.ClickException(f"Invalid container path in {label}: {container} (must be absolute)")

    host_path = Path(host).expanduser()
    if not host_path.exists():
        raise click.ClickException(f"Host path in {label} does not exist: {host}")

    return str(host_path), container


def _normalize_container_project_name(raw_value: str | None, fallback_name: str) -> str:
    candidate = str(raw_value or "").strip() or str(fallback_name or "").strip()
    if not candidate:
        raise click.ClickException("Unable to resolve container project directory name.")
    if "/" in candidate or candidate in {".", ".."}:
        raise click.ClickException(
            f"Invalid container project directory name: {candidate!r} "
            "(must be a single path component)."
        )
    return candidate


def _is_running_inside_container() -> bool:
    return Path("/.dockerenv").exists()


def _validate_daemon_visible_mount_source(path: Path, *, label: str) -> None:
    core_paths.validate_daemon_visible_mount_source(
        path,
        label=label,
        is_running_inside_container=_is_running_inside_container(),
        error_factory=lambda message: MountVisibilityError(message),
    )


def _daemon_mount_source_kind(path: Path) -> str:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{path}:/__agent_cli_mount_probe",
        "alpine:3.20",
        "sh",
        "-lc",
        "if [ -f /__agent_cli_mount_probe ]; then echo file; "
        "elif [ -d /__agent_cli_mount_probe ]; then echo dir; "
        "else echo missing; fi",
    ]
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        return "unknown"
    token = str(result.stdout or "").strip().splitlines()
    if not token:
        return "unknown"
    resolved = token[-1].strip().lower()
    if resolved in {"file", "dir", "missing"}:
        return resolved
    return "unknown"


def _daemon_visible_mount_source(path: Path) -> Path:
    return core_paths.daemon_visible_mount_source(
        path,
        is_running_inside_container=_is_running_inside_container(),
        mapped_tmp_root=str(os.environ.get(AGENT_HUB_TMP_HOST_PATH_ENV) or "").strip(),
        daemon_tmp_mount_root=DAEMON_TMP_MOUNT_ROOT,
    )


def _prepare_daemon_visible_file_mount_source(
    source: Path,
    *,
    label: str,
) -> Path:
    source_path = source.resolve()
    if not source_path.exists() or not source_path.is_file():
        raise MountVisibilityError(f"{label} must reference an existing file: {source_path}")
    _validate_daemon_visible_mount_source(source_path, label=label)
    if not _is_running_inside_container():
        return source_path
    candidate = _daemon_visible_mount_source(source_path)
    _validate_daemon_visible_mount_source(candidate, label=f"{label} (mapped)")
    source_kind = _daemon_mount_source_kind(candidate)
    if source_kind == "file":
        return candidate
    raise MountVisibilityError(
        f"{label} must be daemon-visible as a file but resolved as '{source_kind}': {candidate}. "
        "Fix host/container path mapping before retrying."
    )


def _normalize_container_path(raw_path: str) -> PurePosixPath:
    normalized = posixpath.normpath(str(raw_path or "").strip())
    if not normalized.startswith("/"):
        raise click.ClickException(f"Invalid container path: {raw_path} (must be absolute)")
    return PurePosixPath(normalized)


def _container_path_is_within(path: PurePosixPath, root: PurePosixPath) -> bool:
    if path == root:
        return True
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_mount_inside_project_path(*, spec: str, label: str, container_project_path: PurePosixPath) -> None:
    if ":" not in spec:
        return
    _host, container = spec.split(":", 1)
    container_path = _normalize_container_path(container)
    if _container_path_is_within(container_path, container_project_path):
        raise click.ClickException(
            f"Invalid {label}: {spec}. Container path '{container_path}' is inside the project mount path "
            f"'{container_project_path}', which can cause Docker to create root-owned directories in the checkout. "
            "Mount shared/system paths outside the checkout (for example /workspace/.cache/sccache)."
        )


def _path_metadata(path: Path) -> str:
    try:
        info = path.stat()
    except OSError as exc:
        return f"stat_error={exc}"
    permissions = stat.S_IMODE(info.st_mode)
    return f"uid={info.st_uid} gid={info.st_gid} mode=0o{permissions:03o}"


def _rw_mount_preflight_error(
    *,
    host_path: Path,
    container_path: str,
    reason: str,
    runtime_uid: int,
    runtime_gid: int,
    failing_path: Path | None = None,
) -> None:
    offending = failing_path or host_path
    raise click.ClickException(
        "RW mount preflight failed for "
        f"{host_path} -> {container_path}: {reason}. "
        f"offending_path={offending} ({_path_metadata(offending)}); "
        f"mount_root={host_path} ({_path_metadata(host_path)}); "
        f"runtime_uid_gid={runtime_uid}:{runtime_gid}"
    )


def _ensure_rw_mount_owner(root: Path, container_path: str, runtime_uid: int, runtime_gid: int) -> None:
    try:
        owner_uid = int(root.stat().st_uid)
    except OSError as exc:
        _rw_mount_preflight_error(
            host_path=root,
            container_path=container_path,
            reason=f"cannot stat mount root owner ({exc})",
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            failing_path=root,
        )
    if owner_uid != runtime_uid:
        _rw_mount_preflight_error(
            host_path=root,
            container_path=container_path,
            reason=f"mount root owner uid does not match runtime uid ({owner_uid} != {runtime_uid})",
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            failing_path=root,
        )


def _probe_rw_directory(root: Path, container_path: str, runtime_uid: int, runtime_gid: int) -> None:
    _ensure_rw_mount_owner(root, container_path, runtime_uid, runtime_gid)
    if not os.access(root, os.W_OK | os.X_OK):
        _rw_mount_preflight_error(
            host_path=root,
            container_path=container_path,
            reason="mount root directory is not writable/executable by current runtime user",
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            failing_path=root,
        )
    try:
        fd, probe_path = tempfile.mkstemp(prefix=".agent_cli_rw_probe_", dir=str(root))
        os.close(fd)
        os.unlink(probe_path)
    except OSError as exc:
        _rw_mount_preflight_error(
            host_path=root,
            container_path=container_path,
            reason=f"cannot create and remove probe file in mount root ({exc})",
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            failing_path=root,
        )


def _validate_rw_mount(host_path: Path, container_path: str, runtime_uid: int, runtime_gid: int) -> None:
    if not host_path.exists():
        _rw_mount_preflight_error(
            host_path=host_path,
            container_path=container_path,
            reason="host path does not exist",
            runtime_uid=runtime_uid,
            runtime_gid=runtime_gid,
            failing_path=host_path,
        )
    if host_path.is_dir():
        _probe_rw_directory(host_path, container_path, runtime_uid, runtime_gid)
        return
    if host_path.is_file():
        _ensure_rw_mount_owner(host_path, container_path, runtime_uid, runtime_gid)
        if not os.access(host_path, os.W_OK):
            _rw_mount_preflight_error(
                host_path=host_path,
                container_path=container_path,
                reason="file mount path is not writable",
                runtime_uid=runtime_uid,
                runtime_gid=runtime_gid,
                failing_path=host_path,
            )
        try:
            with host_path.open("ab"):
                pass
        except OSError as exc:
            _rw_mount_preflight_error(
                host_path=host_path,
                container_path=container_path,
                reason=f"cannot open file in append mode ({exc})",
                runtime_uid=runtime_uid,
                runtime_gid=runtime_gid,
                failing_path=host_path,
            )
        return
    _rw_mount_preflight_error(
        host_path=host_path,
        container_path=container_path,
        reason="mount path must be a regular file or directory",
        runtime_uid=runtime_uid,
        runtime_gid=runtime_gid,
        failing_path=host_path,
    )


def _build_snapshot_setup_shell_script(
    setup_script: str,
    *,
    source_project_path: str,
    target_project_path: str,
    runtime_uid: int | None = None,
    runtime_gid: int | None = None,
    enforce_project_writable_for_runtime_user: bool = False,
) -> str:
    normalized_script = (setup_script or "").strip() or ":"
    source_path = shlex.quote(source_project_path)
    target_path = shlex.quote(target_project_path)
    target_parent = shlex.quote(str(PurePosixPath(target_project_path).parent))
    script = (
        "set -e\n"
        "set -o pipefail\n"
        "printf '%s\\n' '[agent_cli] snapshot bootstrap: preparing writable /workspace/tmp'\n"
        "mkdir -p /workspace/tmp\n"
        "printf '%s\\n' '[agent_cli] snapshot bootstrap: configuring git safe.directory'\n"
        "git config --global --add safe.directory '*'\n"
        "printf '%s\\n' '[agent_cli] snapshot bootstrap: copying repository into image workspace'\n"
        f"mkdir -p {target_parent}\n"
        f"rm -rf {target_path}\n"
        f"mkdir -p {target_path}\n"
        f"cp -a {source_path}/. {target_path}/\n"
        f"cd {target_path}\n"
    )
    if runtime_uid is not None and runtime_gid is not None:
        script += (
            "printf '%s\\n' '[agent_cli] snapshot bootstrap: running project setup script as runtime user'\n"
            f"setpriv --reuid {runtime_uid} --regid {runtime_gid} --keep-groups bash -lc {shlex.quote(normalized_script)}\n"
        )
    else:
        script += (
            "printf '%s\\n' '[agent_cli] snapshot bootstrap: running project setup script'\n"
            + normalized_script
            + "\n"
        )
    if enforce_project_writable_for_runtime_user and runtime_uid is not None and runtime_gid is not None:
        writable_probe_cmd = (
            "set -euo pipefail; "
            f"test -d {target_path}; "
            f'project_path={target_path}; '
            'probe_path="$project_path/.agent-cli-write-probe-$$"; '
            ': > "$probe_path"; '
            'rm -f "$probe_path"'
        )
        script += (
            "printf '%s\\n' '[agent_cli] snapshot bootstrap: repairing in-image project ownership "
            f"for {target_project_path} -> {runtime_uid}:{runtime_gid}'\n"
        )
        script += f"chown -R {runtime_uid}:{runtime_gid} {target_path}\n"
        script += (
            "printf '%s\\n' '[agent_cli] snapshot bootstrap: verifying in-image project path is writable "
            f"for {runtime_uid}:{runtime_gid} at {target_project_path}'\n"
        )
        script += (
            f"setpriv --reuid {runtime_uid} --regid {runtime_gid} --keep-groups "
            f"bash -lc {shlex.quote(writable_probe_cmd)}\n"
        )
    return script


def _parse_env_var(spec: str, label: str) -> str:
    if "=" not in spec:
        raise click.ClickException(f"Invalid {label}: {spec} (expected KEY=VALUE)")
    key, value = spec.split("=", 1)
    key = key.strip()
    if not key:
        raise click.ClickException(f"Invalid {label}: {spec} (empty key)")
    if any(ch.isspace() for ch in key):
        raise click.ClickException(f"Invalid {label}: {spec} (key must not contain whitespace)")
    return f"{key}={value}"


def _normalize_agent_command(raw_value: str | None) -> str:
    value = str(raw_value or DEFAULT_AGENT_COMMAND).strip()
    if not value:
        return DEFAULT_AGENT_COMMAND
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise click.ClickException(
            f"Invalid --agent-command value: {raw_value!r} (allowed characters: letters, numbers, . _ -)"
        )
    return value


def _agent_provider_for_command(agent_command: str) -> str:
    command = str(agent_command or "").strip().lower()
    if command == "codex":
        return AGENT_PROVIDER_CODEX
    if command == "claude":
        return AGENT_PROVIDER_CLAUDE
    if command == "gemini":
        return AGENT_PROVIDER_GEMINI
    raise click.ClickException(
        f"Unsupported --agent-command '{agent_command}'. Supported commands: codex, claude, gemini."
    )


def _default_runtime_image_for_provider(agent_provider: str) -> str:
    if agent_provider == AGENT_PROVIDER_CLAUDE:
        return CLAUDE_RUNTIME_IMAGE
    if agent_provider == AGENT_PROVIDER_GEMINI:
        return GEMINI_RUNTIME_IMAGE
    if agent_provider == AGENT_PROVIDER_CODEX:
        return DEFAULT_RUNTIME_IMAGE
    raise click.ClickException(
        f"Unsupported agent provider '{agent_provider}' when selecting runtime image."
    )


def _resolve_requested_run_mode(
    *,
    cli_run_mode: str | None,
    runtime_config: AgentRuntimeConfig,
) -> str:
    return core_build_inputs.resolve_requested_run_mode(
        cli_run_mode=cli_run_mode,
        configured_run_mode=str(runtime_config.runtime.run_mode or ""),
        default_run_mode=DEFAULT_RUNTIME_RUN_MODE,
    )


def _resolve_effective_run_mode(requested_run_mode: str) -> str:
    return core_build_inputs.resolve_effective_run_mode(
        requested_run_mode,
        auto_mode=RUNTIME_RUN_MODE_AUTO,
        docker_mode=RUNTIME_RUN_MODE_DOCKER,
    )


def _validate_run_mode_requirements(*, run_mode: str, agent_command: str) -> None:
    del agent_command
    core_build_inputs.validate_run_mode_requirements(
        run_mode=run_mode,
        docker_mode=RUNTIME_RUN_MODE_DOCKER,
        native_mode=RUNTIME_RUN_MODE_NATIVE,
        run_mode_choices=RUNTIME_RUN_MODE_CHOICES,
        docker_available=shutil.which("docker") is not None,
        error_factory=lambda message: click.ClickException(message),
    )


def _snapshot_runtime_image_for_provider(snapshot_tag: str, agent_provider: str) -> str:
    return f"agent-runtime-{_sanitize_tag_component(agent_provider)}-{_short_hash(snapshot_tag)}"


def _snapshot_setup_runtime_image_for_snapshot(snapshot_tag: str) -> str:
    return core_runtime_images.snapshot_setup_runtime_image_for_snapshot(
        snapshot_tag,
        error_factory=lambda message: click.ClickException(message),
    )


def _runtime_image_build_lock_path(target_image: str) -> Path:
    return core_runtime_images.runtime_image_build_lock_path(
        target_image,
        lock_dir=RUNTIME_IMAGE_BUILD_LOCK_DIR,
    )


@contextmanager
def _runtime_image_build_lock(target_image: str) -> Iterator[None]:
    with core_runtime_images.runtime_image_build_lock(
        target_image,
        lock_dir=RUNTIME_IMAGE_BUILD_LOCK_DIR,
        error_factory=lambda message: click.ClickException(message),
    ):
        yield


def _build_runtime_image(
    *,
    base_image: str,
    target_image: str,
    agent_provider: str,
) -> None:
    click.echo(
        f"Building runtime image '{target_image}' from {DEFAULT_DOCKERFILE} "
        f"(base={base_image}, provider={agent_provider})"
    )
    core_runtime_images.build_runtime_image(
        repo_root=_repo_root(),
        dockerfile=DEFAULT_DOCKERFILE,
        base_image=base_image,
        target_image=target_image,
        agent_provider=agent_provider,
        run_command=_run,
    )


def _ensure_agent_cli_base_image_built() -> None:
    with _runtime_image_build_lock(AGENT_CLI_BASE_IMAGE):
        click.echo(f"Building base image '{AGENT_CLI_BASE_IMAGE}' from {DEFAULT_AGENT_CLI_BASE_DOCKERFILE}")
        core_runtime_images.build_agent_cli_base_image(
            repo_root=_repo_root(),
            base_dockerfile=DEFAULT_AGENT_CLI_BASE_DOCKERFILE,
            base_image=AGENT_CLI_BASE_IMAGE,
            run_command=_run,
        )


def _ensure_runtime_image_built_if_missing(
    *,
    base_image: str,
    target_image: str,
    agent_provider: str,
) -> None:
    core_runtime_images.ensure_runtime_image_built_if_missing(
        base_image=base_image,
        target_image=target_image,
        agent_provider=agent_provider,
        repo_root=_repo_root(),
        runtime_dockerfile=DEFAULT_DOCKERFILE,
        base_dockerfile=DEFAULT_AGENT_CLI_BASE_DOCKERFILE,
        agent_cli_base_image=AGENT_CLI_BASE_IMAGE,
        docker_image_exists=_docker_image_exists,
        run_command=_run,
        lock_dir=RUNTIME_IMAGE_BUILD_LOCK_DIR,
        lock_error_factory=lambda message: click.ClickException(message),
        on_build_base_image=lambda image, dockerfile: click.echo(
            f"Building base image '{image}' from {dockerfile}"
        ),
        on_build_runtime_image=lambda image, dockerfile, source_base, provider: click.echo(
            f"Building runtime image '{image}' from {dockerfile} "
            f"(base={source_base}, provider={provider})"
        ),
    )


def _read_openai_api_key(path: Path) -> str | None:
    return core_runtime_images.read_openai_api_key(path)


def _ensure_claude_json_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise click.ClickException(f"Unable to create parent directory for Claude config file {path}: {exc}") from exc

    if path.exists():
        if not path.is_file():
            raise click.ClickException(f"Claude config path exists but is not a file: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise click.ClickException(f"Unable to read Claude config file {path}: {exc}") from exc
        stripped_raw = raw.strip()
        if stripped_raw:
            try:
                parsed = json.loads(stripped_raw)
                if not isinstance(parsed, dict):
                    raise click.ClickException(f"Claude config file {path} must be a JSON object")
                return
            except json.JSONDecodeError as exc:
                raise click.ClickException(f"Claude config file {path} must be valid JSON: {exc}") from exc

        try:
            path.write_text("{}\n", encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Unable to initialize Claude config file {path}: {exc}") from exc
        return
    try:
        path.write_text("{}\n", encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Unable to initialize Claude config file {path}: {exc}") from exc


def _ensure_gemini_settings_file(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise click.ClickException(f"Unable to create parent directory for Gemini settings file {path}: {exc}") from exc

    if path.exists():
        if not path.is_file():
            raise click.ClickException(f"Gemini settings path exists but is not a file: {path}")
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise click.ClickException(f"Unable to read Gemini settings file {path}: {exc}") from exc

        stripped_raw = raw.strip()
        if stripped_raw:
            try:
                parsed = json.loads(stripped_raw)
                if not isinstance(parsed, dict):
                    raise click.ClickException(f"Gemini settings file {path} must be a JSON object")
                return
            except json.JSONDecodeError as exc:
                raise click.ClickException(f"Gemini settings file {path} must be valid JSON: {exc}") from exc
        try:
            path.write_text("{}", encoding="utf-8")
        except OSError as exc:
            raise click.ClickException(f"Unable to initialize Gemini settings file {path}: {exc}") from exc
        return
    try:
        path.write_text("{}", encoding="utf-8")
    except OSError as exc:
        raise click.ClickException(f"Unable to initialize Gemini settings file {path}: {exc}") from exc


def _normalize_git_credential_host(raw_value: str) -> str:
    candidate = str(raw_value or "").strip().lower()
    if not candidate:
        raise click.ClickException("Git credential host is required.")
    host = candidate
    if "://" in candidate:
        parsed = urllib.parse.urlsplit(candidate)
        scheme = _normalize_git_credential_scheme(parsed.scheme)
        del scheme
        if parsed.username or parsed.password:
            raise click.ClickException(f"Invalid git credential host: {raw_value}")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise click.ClickException(f"Invalid git credential host: {raw_value}")
        host_name = str(parsed.hostname or "").strip().lower()
        if not host_name:
            raise click.ClickException(f"Invalid git credential host: {raw_value}")
        host = f"{host_name}:{parsed.port}" if parsed.port else host_name

    host_name, port = _split_host_port(host)
    if not re.fullmatch(r"[a-z0-9.-]+", host_name):
        raise click.ClickException(f"Invalid git credential host: {raw_value}")
    return f"{host_name}:{port}" if port else host_name


def _resolve_base_image(
    base_docker_path: str | None,
    base_docker_context: str | None,
    base_dockerfile: str | None,
    project_dir: Path,
    cwd: Path,
) -> tuple[str, Path, Path] | tuple[None, None, None]:
    return core_build_inputs.resolve_base_image(
        base_docker_path=base_docker_path,
        base_docker_context=base_docker_context,
        base_dockerfile=base_dockerfile,
        project_dir=project_dir,
        cwd=cwd,
        to_absolute=_to_absolute,
        sanitize_tag_component=_sanitize_tag_component,
        short_hash=_short_hash,
        error_factory=lambda message: click.ClickException(message),
    )


def _validate_base_image_source_flags(
    *,
    base_docker_path: str | None,
    base_docker_context: str | None,
    base_dockerfile: str | None,
    base_image: str,
    base_image_tag: str | None,
) -> None:
    core_build_inputs.validate_base_image_source_flags(
        base_docker_path=base_docker_path,
        base_docker_context=base_docker_context,
        base_dockerfile=base_dockerfile,
        base_image=base_image,
        base_image_tag=base_image_tag,
        default_base_image=DEFAULT_BASE_IMAGE,
        error_factory=lambda message: click.ClickException(message),
    )


@click.command(help="Launch the containerized agent environment")
@click.option("--project", default=".", show_default=True)
@click.option(
    "--agent-command",
    default=DEFAULT_AGENT_COMMAND,
    show_default=True,
    help="Agent executable launched inside the container (for example codex, claude, or gemini)",
)
@click.option(
    "--run-mode",
    type=click.Choice(RUNTIME_RUN_MODE_CHOICES, case_sensitive=False),
    default=None,
    help="Runtime mode override. If omitted, uses config runtime.run_mode (default: docker).",
)
@click.option("--container-home", default=None, help="Container home path for mapped user")
@click.option(
    "--container-project-name",
    default=None,
    help="Container-side project directory name under --container-home (defaults to host project directory name).",
)
@click.option("--agent-home-path", default=None, help="Host path for persistent agent state")
@click.option(
    "--config-file",
    default=str(_default_config_file()),
    show_default=True,
    help="Host agent config file mounted into container",
)
@click.option(
    "--system-prompt-file",
    default=str(_default_system_prompt_file()),
    show_default=True,
    help="Core system prompt markdown file used across Codex, Claude, and Gemini sessions.",
)
@click.option("--openai-api-key", default=None, show_default=False, help="API key to pass into container")
@click.option(
    "--credentials-file",
    default=str(_default_credentials_file()),
    show_default=True,
    help="Fallback credentials file to read OPENAI_API_KEY",
)
@click.option(
    "--base",
    "base_docker_path",
    default=None,
    help="Dockerfile path or directory containing a Dockerfile",
)
@click.option("--base-docker-context", default=None, help="Base Dockerfile context directory")
@click.option("--base-dockerfile", default=None, help="Base Dockerfile (relative to context or absolute)")
@click.option("--base-image", default=DEFAULT_BASE_IMAGE, show_default=True)
@click.option("--base-image-tag", default=None, help="Tag for generated base image")
@click.option("--local-user", default=None)
@click.option("--local-group", default=None)
@click.option("--local-uid", default=None, type=int)
@click.option("--local-gid", default=None, type=int)
@click.option("--local-supplementary-gids", default=None, help="Comma-separated supplemental GIDs")
@click.option("--local-supplementary-groups", default=None, help="Comma-separated supplemental group names")
@click.option(
    "--bootstrap-as-root",
    is_flag=True,
    default=False,
    help="Start container as root, then drop to --local-uid/--local-gid inside entrypoint after workspace ownership bootstrap.",
)
@click.option("--local-umask", default="0022")
@click.option("--ro-mount", "ro_mounts", multiple=True, help="Host:container read-only mount")
@click.option("--rw-mount", "rw_mounts", multiple=True, help="Host:container read-write mount")
@click.option("--env-var", "env_vars", multiple=True, help="Additional environment variable KEY=VALUE")
@click.option(
    "--setup-script",
    default=None,
    help="Multiline setup commands run sequentially in the container project directory.",
)
@click.option(
    "--snapshot-image-tag",
    default=None,
    help="Project setup snapshot image tag. If present, this image is reused or built once from setup script.",
)
@click.option(
    "--prepare-snapshot-only",
    is_flag=True,
    default=False,
    help="Build/reuse snapshot image and exit without starting the agent.",
)
@click.option(
    "--project-in-image",
    is_flag=True,
    default=False,
    help="Run without bind-mounting --project; expects repository to already exist in the runtime image.",
)
@click.option(
    "--no-alt-screen",
    is_flag=True,
    default=False,
    help="Pass --no-alt-screen to codex when launching the agent.",
)
@click.option(
    "--tty/--no-tty",
    "allocate_tty",
    default=True,
    show_default=True,
    help="Allocate a pseudo-TTY for docker run.",
)
@click.option(
    "--rw-mount-preflight",
    "run_rw_mount_preflight",
    is_flag=True,
    default=False,
    hidden=True,
)
@click.option("--resume", is_flag=True, default=False, help="Resume last session")
@click.argument("container_args", nargs=-1)
def main(
    project: str,
    agent_command: str,
    run_mode: str | None,
    container_home: str | None,
    container_project_name: str | None,
    agent_home_path: str | None,
    config_file: str,
    system_prompt_file: str,
    openai_api_key: str | None,
    credentials_file: str,
    base_docker_path: str | None,
    base_docker_context: str | None,
    base_dockerfile: str | None,
    base_image: str,
    base_image_tag: str | None,
    local_user: str | None,
    local_group: str | None,
    local_uid: int | None,
    local_gid: int | None,
    local_supplementary_gids: str | None,
    local_supplementary_groups: str | None,
    bootstrap_as_root: bool,
    local_umask: str,
    ro_mounts: tuple[str, ...],
    rw_mounts: tuple[str, ...],
    env_vars: tuple[str, ...],
    setup_script: str | None,
    snapshot_image_tag: str | None,
    prepare_snapshot_only: bool,
    project_in_image: bool,
    no_alt_screen: bool,
    allocate_tty: bool,
    run_rw_mount_preflight: bool,
    resume: bool,
    container_args: tuple[str, ...],
) -> None:
    cwd = Path.cwd().resolve()
    project_path = _to_absolute(project, cwd)
    if not project_path.is_dir():
        raise click.ClickException(f"Project path does not exist: {project_path}")
    _validate_base_image_source_flags(
        base_docker_path=base_docker_path,
        base_docker_context=base_docker_context,
        base_dockerfile=base_dockerfile,
        base_image=base_image,
        base_image_tag=base_image_tag,
    )

    config_path = _to_absolute(config_file, cwd)
    if not config_path.is_file():
        raise click.ClickException(f"Agent config file does not exist: {config_path}")
    try:
        runtime_config = load_agent_runtime_config(config_path)
    except ConfigError as exc:
        click.echo(
            json.dumps(
                {
                    "event": "agent_cli_config_load_error",
                    "config_path": str(config_path),
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise click.ClickException(str(exc)) from exc
    click.echo(
        json.dumps(
            {
                "event": "agent_cli_config_loaded",
                "config_path": str(config_path),
                "run_mode": str(runtime_config.runtime.run_mode or ""),
            },
            sort_keys=True,
        ),
        err=True,
    )
    selected_agent_command = _normalize_agent_command(agent_command)
    selected_agent_provider = _agent_provider_for_command(selected_agent_command)
    requested_run_mode = _resolve_requested_run_mode(cli_run_mode=run_mode, runtime_config=runtime_config)
    effective_run_mode = _resolve_effective_run_mode(requested_run_mode)
    _validate_run_mode_requirements(run_mode=effective_run_mode, agent_command=selected_agent_command)
    if effective_run_mode != RUNTIME_RUN_MODE_DOCKER:
        raise click.ClickException(
            f"run_mode={effective_run_mode} is not supported for dockerized agent_cli execution."
        )

    try:
        _validate_daemon_visible_mount_source(project_path, label="--project")
        daemon_project_path = _daemon_visible_mount_source(project_path)
        _validate_daemon_visible_mount_source(config_path, label="--config-file")
    except MountVisibilityError as exc:
        raise click.ClickException(str(exc)) from exc

    system_prompt_path = _to_absolute(system_prompt_file, cwd)
    if not system_prompt_path.is_file():
        raise click.ClickException(f"System prompt file does not exist: {system_prompt_path}")
    try:
        _validate_daemon_visible_mount_source(system_prompt_path, label="--system-prompt-file")
    except MountVisibilityError as exc:
        raise click.ClickException(str(exc)) from exc
    core_system_prompt = _read_system_prompt(system_prompt_path)

    explicit_supplementary_gids: str | None = None
    if local_supplementary_gids is not None:
        explicit_supplementary_gids = local_supplementary_gids
    elif local_supplementary_groups is not None:
        explicit_supplementary_gids = _group_names_to_gid_csv(local_supplementary_groups)
    explicit_gid = local_gid
    if explicit_gid is None and local_group:
        explicit_gid = _gid_for_group_name(local_group)

    try:
        runtime_identity = core_identity.resolve_runtime_identity(
            core_identity.RuntimeIdentityResolutionContract(
                runtime_config=runtime_config,
                explicit_uid=local_uid,
                explicit_gid=explicit_gid,
                explicit_username=str(local_user or "").strip(),
                explicit_supplementary_gids=explicit_supplementary_gids,
                default_uid=os.getuid(),
                default_gid=os.getgid(),
                default_supplementary_gids=_default_supplementary_gids(),
                umask=local_umask,
            ),
            username_lookup=lambda lookup_uid: pwd.getpwuid(int(lookup_uid)).pw_name,
            missing_username_message_factory=(
                lambda lookup_uid: (
                    f"Unable to resolve host username for uid={lookup_uid}. Pass --local-user explicitly."
                )
            ),
            error_factory=lambda message: IdentityError(message),
        )
    except IdentityError as exc:
        raise click.ClickException(str(exc)) from exc

    uid = int(runtime_identity.uid)
    gid = int(runtime_identity.gid)
    user = runtime_identity.username
    supp_gids_csv = runtime_identity.supplementary_gids
    supplemental_group_ids = [supp_gid for supp_gid in _parse_gid_csv(supp_gids_csv) if supp_gid != gid]
    docker_socket_gid = _docker_socket_gid()
    if (
        docker_socket_gid is not None
        and docker_socket_gid != gid
        and docker_socket_gid not in supplemental_group_ids
    ):
        supplemental_group_ids.append(docker_socket_gid)

    container_home_path = str(container_home or DEFAULT_CONTAINER_HOME).strip() or DEFAULT_CONTAINER_HOME
    if not container_home_path.startswith("/"):
        raise click.ClickException(f"Invalid --container-home: {container_home_path} (must be absolute)")
    resolved_container_project_name = _normalize_container_project_name(container_project_name, project_path.name)
    container_project_path = str(_normalize_container_path(str(PurePosixPath(container_home_path) / resolved_container_project_name)))
    container_project_root = _normalize_container_path(container_project_path)

    default_agent_home = _resolved_agent_hub_data_dir(runtime_config) / "agent-home" / user
    host_agent_home = Path(agent_home_path or default_agent_home).resolve()
    _validate_daemon_visible_mount_source(host_agent_home, label="--agent-home-path")
    host_codex_dir = host_agent_home / ".codex"
    host_claude_dir = host_agent_home / ".claude"
    host_claude_json_file = host_agent_home / ".claude.json"
    host_claude_config_dir = host_agent_home / ".config" / "claude"
    host_gemini_dir = host_agent_home / ".gemini"
    host_gemini_settings_file = host_gemini_dir / GEMINI_SETTINGS_FILE_NAME
    host_codex_dir.mkdir(parents=True, exist_ok=True)
    host_claude_dir.mkdir(parents=True, exist_ok=True)
    _ensure_claude_json_file(host_claude_json_file)
    _ensure_gemini_settings_file(host_gemini_settings_file)
    host_claude_config_dir.mkdir(parents=True, exist_ok=True)
    host_gemini_dir.mkdir(parents=True, exist_ok=True)
    (host_agent_home / "projects").mkdir(parents=True, exist_ok=True)

    api_key = openai_api_key
    if not api_key:
        api_key = _read_openai_api_key(_to_absolute(credentials_file, cwd))
    snapshot_tag = (snapshot_image_tag or "").strip()
    if project_in_image and not snapshot_tag:
        raise click.ClickException("--project-in-image requires --snapshot-image-tag")
    cached_snapshot_exists = bool(snapshot_tag) and _docker_image_exists(snapshot_tag)
    if cached_snapshot_exists:
        click.echo(f"Using cached setup snapshot image '{snapshot_tag}'")

    build_service = BuildService(
        base_image=base_image,
        base_image_tag=base_image_tag,
        base_docker_path=base_docker_path,
        base_docker_context=base_docker_context,
        base_dockerfile=base_dockerfile,
        project_path=project_path,
        cwd=cwd,
        agent_cli_base_image=AGENT_CLI_BASE_IMAGE,
        resolve_base_image=_resolve_base_image,
        run_command=_run,
        ensure_agent_cli_base_image_built=_ensure_agent_cli_base_image_built,
        sanitize_tag_component=_sanitize_tag_component,
        short_hash=_short_hash,
        click_echo=click.echo,
    )

    shared_prompt_context = _shared_prompt_context_from_runtime_config(
        runtime_config,
        core_system_prompt=core_system_prompt,
    )
    
    try:
        agent_provider = agent_providers.get_provider(selected_agent_provider)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    agent_provider.sync_shared_context_file(
        host_agent_home=host_agent_home / f".{agent_provider.name}",
        shared_prompt_context=shared_prompt_context,
    )

    execute_launch_pipeline(
        data=LaunchPipelineInput(
            ro_mounts=ro_mounts,
            rw_mounts=rw_mounts,
            env_vars=env_vars,
            container_args=container_args,
            selected_agent_provider=selected_agent_provider,
            selected_agent_command=selected_agent_command,
            no_alt_screen=no_alt_screen,
            resume=resume,
            snapshot_tag=snapshot_tag,
            prepare_snapshot_only=prepare_snapshot_only,
            project_in_image=project_in_image,
            setup_script=setup_script,
            cached_snapshot_exists=cached_snapshot_exists,
            project_path=project_path,
            daemon_project_path=daemon_project_path,
            container_project_path=container_project_path,
            container_project_root=container_project_root,
            config_path=config_path,
            system_prompt_path=system_prompt_path,
            host_codex_dir=host_codex_dir,
            host_claude_dir=host_claude_dir,
            host_claude_json_file=host_claude_json_file,
            host_claude_config_dir=host_claude_config_dir,
            host_gemini_dir=host_gemini_dir,
            host_gemini_settings_file=host_gemini_settings_file,
            container_home_path=container_home_path,
            runtime_identity=runtime_identity,
            supplemental_group_ids=supplemental_group_ids,
            bootstrap_as_root=bootstrap_as_root,
            api_key=api_key,
            runtime_config=runtime_config,
            effective_run_mode=effective_run_mode,
            allocate_tty=allocate_tty,
            shared_prompt_context=shared_prompt_context,
            run_rw_mount_preflight=run_rw_mount_preflight,
        ),
        deps=LaunchPipelineDeps(
            click_echo=click.echo,
            parse_mount=_parse_mount,
            parse_env_var=_parse_env_var,
            reject_mount_inside_project_path=_reject_mount_inside_project_path,
            validate_daemon_visible_mount_source=_validate_daemon_visible_mount_source,
            daemon_visible_mount_source=_daemon_visible_mount_source,
            validate_rw_mount=_validate_rw_mount,
            prepare_daemon_visible_file_mount_source=_prepare_daemon_visible_file_mount_source,
            has_codex_config_override=_has_codex_config_override,
            resolved_runtime_term=_resolved_runtime_term,
            resolved_runtime_colorterm=_resolved_runtime_colorterm,
            platform_startswith_linux=lambda: sys.platform.startswith("linux"),
            default_runtime_image_for_provider=_default_runtime_image_for_provider,
            snapshot_setup_runtime_image_for_snapshot=_snapshot_setup_runtime_image_for_snapshot,
            snapshot_runtime_image_for_provider=_snapshot_runtime_image_for_provider,
            ensure_runtime_image_built_if_missing=_ensure_runtime_image_built_if_missing,
            build_runtime_image=_build_runtime_image,
            build_snapshot_setup_shell_script=_build_snapshot_setup_shell_script,
            sanitize_tag_component=_sanitize_tag_component,
            short_hash=_short_hash,
            docker_rm_force=_docker_rm_force,
            run_command=_run,
            start_agent_tools_runtime_bridge=_start_agent_tools_runtime_bridge,
            compile_docker_run_command=core_launch.compile_docker_run_command,
            docker_run_plan_factory=core_launch.DockerRunInvocationPlan,
            snapshot_source_project_path=SNAPSHOT_SOURCE_PROJECT_PATH,
            default_container_home=DEFAULT_CONTAINER_HOME,
            agent_provider_none=AGENT_PROVIDER_NONE,
            agent_provider_codex=AGENT_PROVIDER_CODEX,
            agent_provider_claude=AGENT_PROVIDER_CLAUDE,
            agent_provider_gemini=AGENT_PROVIDER_GEMINI,
            docker_socket_path=DOCKER_SOCKET_PATH,
            tmp_dir_tmpfs_spec=TMP_DIR_TMPFS_SPEC,
        ),
        build_service=build_service,
        agent_provider=agent_provider,
    )


if __name__ == "__main__":
    main()
