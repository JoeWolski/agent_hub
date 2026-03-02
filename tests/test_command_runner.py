from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core.errors import RuntimeCommandError
from agent_hub.integrations.command_runner import run_command


def test_run_command_raises_runtime_command_error_on_non_zero_exit_when_check_true() -> None:
    with patch("agent_hub.integrations.command_runner.subprocess.run") as run_mock:
        run_mock.return_value = subprocess.CompletedProcess(
            ["uv", "run", "agent_hub"],
            5,
            stdout="failed output\n",
            stderr="more context\n",
        )
        try:
            run_command(["uv", "run", "agent_hub"], capture=True, check=True)
            raise AssertionError("expected RuntimeCommandError")
        except RuntimeCommandError as exc:
            assert exc.error_code == "RUNTIME_COMMAND_ERROR"
            assert exc.failure_class == "runtime_command"
            assert exc.http_status == 400
            assert "uv run agent_hub" in str(exc)
            assert "exit code 5" in str(exc)


def test_run_command_allows_non_zero_exit_when_check_false() -> None:
    with patch("agent_hub.integrations.command_runner.subprocess.run") as run_mock:
        expected = subprocess.CompletedProcess(["echo", "x"], 1, stdout="", stderr="")
        run_mock.return_value = expected
        result = run_command(["echo", "x"], capture=True, check=False)
    assert result is expected
