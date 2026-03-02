from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core import shared


class _SharedError(RuntimeError):
    pass


def _error_factory(message: str) -> Exception:
    return _SharedError(message)


def test_repo_root_finds_pyproject_ancestor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    start_dir = repo / "src" / "agent_cli"
    start_dir.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    start_file = start_dir / "cli.py"
    start_file.write_text("", encoding="utf-8")

    assert shared.repo_root(start_file) == repo


def test_repo_root_falls_back_to_start_parent_without_pyproject(tmp_path: Path) -> None:
    start_dir = tmp_path / "a" / "b"
    start_dir.mkdir(parents=True)
    start_file = start_dir / "x.py"
    start_file.write_text("", encoding="utf-8")

    assert shared.repo_root(start_file) == start_dir


def test_default_config_file_is_canonical_repo_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    cwd = tmp_path / "cwd"
    (repo_root / "config").mkdir(parents=True)
    (cwd / "config").mkdir(parents=True)

    repo_cfg = repo_root / "config" / "agent.config.toml"
    cwd_cfg = cwd / "config" / "agent.config.toml"

    repo_cfg.write_text("x=1\n", encoding="utf-8")
    cwd_cfg.write_text("x=2\n", encoding="utf-8")
    assert shared.default_config_file(repo_root, cwd=cwd) == repo_cfg

    repo_cfg.unlink()
    assert shared.default_config_file(repo_root, cwd=cwd) == repo_cfg

    cwd_cfg.unlink()
    assert shared.default_config_file(repo_root, cwd=cwd) == repo_cfg


def test_default_system_prompt_file_is_canonical_repo_path(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    cwd = tmp_path / "cwd"
    repo_root.mkdir(parents=True)
    cwd.mkdir(parents=True)
    name = "SYSTEM_PROMPT.md"

    repo_prompt = repo_root / name
    cwd_prompt = cwd / name

    repo_prompt.write_text("repo", encoding="utf-8")
    cwd_prompt.write_text("cwd", encoding="utf-8")
    assert shared.default_system_prompt_file(repo_root, name, cwd=cwd) == repo_prompt

    repo_prompt.unlink()
    assert shared.default_system_prompt_file(repo_root, name, cwd=cwd) == repo_prompt

    cwd_prompt.unlink()
    assert shared.default_system_prompt_file(repo_root, name, cwd=cwd) == repo_prompt


def test_split_host_port_parses_and_normalizes() -> None:
    assert shared.split_host_port("", error_factory=_error_factory) == ("", None)
    assert shared.split_host_port("Example.COM", error_factory=_error_factory) == ("example.com", None)
    assert shared.split_host_port("EXAMPLE.com:443", error_factory=_error_factory) == ("example.com", 443)


def test_split_host_port_raises_for_invalid_values() -> None:
    with pytest.raises(_SharedError, match="Invalid git credential host: bad:xyz"):
        shared.split_host_port("bad:xyz", error_factory=_error_factory)
    with pytest.raises(_SharedError, match="Invalid git credential host: bad:70000"):
        shared.split_host_port("bad:70000", error_factory=_error_factory)


def test_docker_image_exists_delegates_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _run_ok(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0)

    def _run_missing(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=[], returncode=1)

    monkeypatch.setattr(shared.subprocess, "run", _run_ok)
    assert shared.docker_image_exists("img:ok") is True

    monkeypatch.setattr(shared.subprocess, "run", _run_missing)
    assert shared.docker_image_exists("img:missing") is False


def test_normalize_csv_trims_and_drops_empty() -> None:
    assert shared.normalize_csv(None) == ""
    assert shared.normalize_csv("  a, ,b,, c ") == "a,b,c"


def test_parse_gid_csv_non_strict_skips_invalid_and_dedupes() -> None:
    assert shared.parse_gid_csv("1, 2, junk, 2, 03, , 0x4", strict=False, error_factory=_error_factory) == [1, 2, 3]


def test_parse_gid_csv_strict_raises_on_invalid() -> None:
    with pytest.raises(_SharedError, match="Invalid supplemental GID: 'junk'"):
        shared.parse_gid_csv("1,junk,2", strict=True, error_factory=_error_factory)
