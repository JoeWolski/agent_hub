from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core import load_agent_runtime_config_dict
from agent_core import identity as core_identity


class _IdentityError(RuntimeError):
    pass


def _error_factory(message: str) -> Exception:
    return _IdentityError(message)


def _runtime_config(identity: dict[str, object] | None = None):
    return load_agent_runtime_config_dict(
        {
            "identity": dict(identity or {}),
            "paths": {},
            "providers": {"defaults": {}},
            "mcp": {},
            "auth": {},
            "logging": {},
            "runtime": {},
        }
    )


def test_parse_runtime_identity_config_reads_aliases_and_normalizes_csv() -> None:
    runtime_config = _runtime_config(
        {
            "uid": "1010",
            "gid": "2020",
            "username": "agent-user",
            "supplementary_gids": " 3000, ,3001, 3000 ",
            "shared_root": "/tmp/shared",
        }
    )

    parsed = core_identity.parse_runtime_identity_config(runtime_config)

    assert parsed.uid_raw == "1010"
    assert parsed.gid_raw == "2020"
    assert parsed.username == "agent-user"
    assert parsed.supplementary_gids == "3000,3001,3000"
    assert parsed.shared_root == "/tmp/shared"


def test_parse_configured_uid_gid_requires_both_values() -> None:
    runtime_config = _runtime_config({"uid": "1234"})
    parsed = core_identity.parse_runtime_identity_config(runtime_config)

    with pytest.raises(_IdentityError, match="identity.uid and identity.gid must be set together"):
        core_identity.parse_configured_uid_gid(parsed, error_factory=_error_factory)


def test_parse_configured_uid_gid_returns_none_when_not_configured() -> None:
    parsed = core_identity.parse_runtime_identity_config(_runtime_config())
    assert core_identity.parse_configured_uid_gid(parsed, error_factory=_error_factory) == (None, None)


def test_parse_non_negative_int_value_rejects_negative_numbers() -> None:
    with pytest.raises(_IdentityError, match="Invalid identity.uid"):
        core_identity.parse_non_negative_int_value(
            "-1",
            source_name="identity.uid",
            error_factory=_error_factory,
        )
