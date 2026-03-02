from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    config_file: Path | None = None
    system_prompt_file: Path | None = None
    workspace_root: Path | None = None
    tmp_root: Path | None = None


def daemon_visible_mount_source(
    path: Path,
    *,
    is_running_inside_container: bool,
    mapped_tmp_root: str = "",
    daemon_tmp_mount_root: Path = Path("/workspace/tmp"),
) -> Path:
    source = path.resolve()
    if not is_running_inside_container:
        return source
    mapped_root = str(mapped_tmp_root or "").strip()
    if not mapped_root:
        return source
    try:
        relative = source.relative_to(daemon_tmp_mount_root.resolve())
    except ValueError:
        return source
    return Path(mapped_root) / relative


def validate_daemon_visible_mount_source(
    path: Path,
    *,
    label: str,
    is_running_inside_container: bool,
    error_factory: Callable[[str], Exception],
) -> None:
    if not is_running_inside_container:
        return
    normalized = path.resolve()
    for disallowed_root in (Path("/tmp"), Path("/var/tmp")):
        if normalized == disallowed_root or disallowed_root in normalized.parents:
            raise error_factory(
                f"{label} must not use container-local '{disallowed_root}' when launching via a host Docker daemon. "
                f"resolved_path={normalized}. "
                "Use a daemon-visible path (for example under /workspace or a bind-mounted project directory)."
            )


def default_agent_hub_data_dir(home: Path | None = None) -> Path:
    resolved_home = (home or Path.home()).expanduser()
    return resolved_home / ".local" / "share" / "agent_hub"


def resolve_agent_hub_data_dir(paths_values: Mapping[str, Any] | None) -> Path:
    if paths_values is not None:
        configured = str(paths_values.get("agent_hub_data_dir") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
    return default_agent_hub_data_dir()
