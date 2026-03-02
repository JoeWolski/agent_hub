from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path


def repo_root(start_file: Path) -> Path:
    resolved = start_file.resolve()
    for parent in resolved.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return resolved.parent


def default_config_file(repo_root: Path, cwd: Path | None = None) -> Path:
    del cwd
    config_file = repo_root / "config" / "agent.config.toml"
    return config_file


def default_system_prompt_file(
    repo_root: Path,
    system_prompt_file_name: str,
    cwd: Path | None = None,
) -> Path:
    del cwd
    prompt_file = repo_root / str(system_prompt_file_name)
    return prompt_file


def split_host_port(host: str, *, error_factory: Callable[[str], Exception]) -> tuple[str, int | None]:
    candidate = str(host or "").strip().lower()
    if not candidate:
        return "", None
    if ":" not in candidate:
        return candidate, None
    hostname, port_text = candidate.rsplit(":", 1)
    if not hostname or not port_text.isdigit():
        raise error_factory(f"Invalid git credential host: {host}")
    port = int(port_text)
    if port <= 0 or port > 65535:
        raise error_factory(f"Invalid git credential host: {host}")
    return hostname, port


def docker_image_exists(tag: str) -> bool:
    result = subprocess.run(
        ["docker", "image", "inspect", tag],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def normalize_csv(value: str | None) -> str:
    if value is None:
        return ""
    values = [part.strip() for part in value.split(",") if part.strip()]
    return ",".join(values)


def parse_gid_csv(value: str, *, strict: bool, error_factory: Callable[[str], Exception]) -> list[int]:
    gids: list[int] = []
    seen: set[int] = set()
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        if not token.isdigit():
            if strict:
                raise error_factory(f"Invalid supplemental GID: {token!r}")
            continue
        gid = int(token, 10)
        if gid in seen:
            continue
        gids.append(gid)
        seen.add(gid)
    return gids
