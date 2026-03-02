from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    config_file: Path | None = None
    system_prompt_file: Path | None = None
    workspace_root: Path | None = None
    tmp_root: Path | None = None


def default_agent_hub_data_dir(home: Path | None = None) -> Path:
    resolved_home = (home or Path.home()).expanduser()
    return resolved_home / ".local" / "share" / "agent_hub"


def resolve_agent_hub_data_dir(paths_values: Mapping[str, Any] | None) -> Path:
    if paths_values is not None:
        configured = str(paths_values.get("agent_hub_data_dir") or "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
    return default_agent_hub_data_dir()

