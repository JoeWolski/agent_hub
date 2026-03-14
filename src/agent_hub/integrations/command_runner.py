from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent_core.errors import RuntimeCommandError


def run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    capture: bool = False,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    resolved_env: dict[str, str] | None = None
    if env:
        resolved_env = dict(os.environ)
        for key, value in env.items():
            resolved_env[str(key)] = str(value)
    result = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=capture,
        env=resolved_env,
    )
    if check and result.returncode != 0:
        message = (result.stdout or "") + (result.stderr or "")
        raise RuntimeCommandError(
            command=cmd,
            exit_code=result.returncode,
            output=message,
        )
    return result
