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


def test_resolve_runtime_supplementary_gids_prefers_explicit_value_even_when_empty() -> None:
    assert (
        core_identity.resolve_runtime_supplementary_gids(
            core_identity.RuntimeIdentityResolverContract(
                explicit_supplementary_gids="",
                configured_supplementary_gids="3000,3001",
                default_supplementary_gids="4000",
            )
        )
        == ""
    )


def test_resolve_runtime_supplementary_gids_falls_back_from_configured_to_default() -> None:
    assert (
        core_identity.resolve_runtime_supplementary_gids(
            core_identity.RuntimeIdentityResolverContract(
                explicit_supplementary_gids=None,
                configured_supplementary_gids="",
                default_supplementary_gids=" 2000, 2001 ",
            )
        )
        == "2000,2001"
    )


def test_resolve_runtime_username_prefers_first_configured_candidate() -> None:
    assert (
        core_identity.resolve_runtime_username(
            core_identity.RuntimeIdentityResolverContract(
                username_candidates=(" configured-user ", "fallback-user"),
                uid_for_username=1234,
            ),
            username_lookup=lambda _uid: "lookup-user",
            error_factory=_error_factory,
            missing_username_message_factory=lambda uid: f"missing user for uid={uid}",
        )
        == "configured-user"
    )


def test_resolve_runtime_username_uses_lookup_when_candidates_empty() -> None:
    assert (
        core_identity.resolve_runtime_username(
            core_identity.RuntimeIdentityResolverContract(
                username_candidates=("", " "),
                uid_for_username=2048,
            ),
            username_lookup=lambda uid: f"user-{uid}",
            error_factory=_error_factory,
            missing_username_message_factory=lambda uid: f"missing user for uid={uid}",
        )
        == "user-2048"
    )


def test_resolve_runtime_username_raises_with_factory_message_on_lookup_error() -> None:
    def _raise_missing(_uid: int) -> str:
        raise KeyError("missing")

    with pytest.raises(_IdentityError, match="missing user for uid=777"):
        core_identity.resolve_runtime_username(
            core_identity.RuntimeIdentityResolverContract(
                username_candidates=(),
                uid_for_username=777,
            ),
            username_lookup=_raise_missing,
            error_factory=_error_factory,
            missing_username_message_factory=lambda uid: f"missing user for uid={uid}",
        )


def test_resolve_runtime_identity_prefers_configured_uid_gid_and_uses_default_supplementary() -> None:
    runtime_config = _runtime_config(
        {
            "uid": "1234",
            "gid": "2345",
            "supplementary_gids": "",
        }
    )

    resolved = core_identity.resolve_runtime_identity(
        core_identity.RuntimeIdentityResolutionContract(
            runtime_config=runtime_config,
            override_uid_raw="3333",
            override_gid_raw="4444",
            override_supplementary_gids="4000,4001",
            default_uid=1000,
            default_gid=1001,
            default_supplementary_gids="5000,5001",
        ),
        resolve_username=False,
        error_factory=_error_factory,
    )

    assert resolved.uid == 1234
    assert resolved.gid == 2345
    assert resolved.supplementary_gids == "5000,5001"


def test_resolve_runtime_identity_uses_override_uid_gid_and_override_supplementary() -> None:
    resolved = core_identity.resolve_runtime_identity(
        core_identity.RuntimeIdentityResolutionContract(
            runtime_config=_runtime_config(),
            override_uid_raw="1111",
            override_gid_raw="2222",
            override_supplementary_gids="3000,3001",
            default_uid=1000,
            default_gid=1001,
            default_supplementary_gids="5000",
        ),
        resolve_username=False,
        error_factory=_error_factory,
    )

    assert resolved.uid == 1111
    assert resolved.gid == 2222
    assert resolved.supplementary_gids == "3000,3001"


def test_resolve_runtime_identity_supports_explicit_uid_gid_override_after_configured() -> None:
    runtime_config = _runtime_config(
        {
            "uid": "1234",
            "gid": "2345",
            "username": "config-user",
        }
    )

    resolved = core_identity.resolve_runtime_identity(
        core_identity.RuntimeIdentityResolutionContract(
            runtime_config=runtime_config,
            explicit_uid=4444,
            explicit_gid=5555,
            explicit_username="",
            default_uid=1000,
            default_gid=1001,
            default_supplementary_gids="6000",
        ),
        username_lookup=lambda lookup_uid: f"user-{lookup_uid}",
        error_factory=_error_factory,
    )

    assert resolved.uid == 4444
    assert resolved.gid == 5555
    assert resolved.username == "config-user"


def test_resolve_runtime_identity_uses_shared_root_candidate_and_formats_stat_error() -> None:
    def _raise_stat(_path: str):
        raise OSError("boom")

    with pytest.raises(_IdentityError, match=r"Failed to stat AGENT_HUB_SHARED_ROOT='/.+/shared': boom"):
        core_identity.resolve_runtime_identity(
            core_identity.RuntimeIdentityResolutionContract(
                runtime_config=_runtime_config(),
                shared_root_candidates=("/tmp/shared",),
                default_uid=1000,
                default_gid=1001,
            ),
            resolve_username=False,
            stat_lookup=_raise_stat,
            stat_error_message_factory=lambda path, exc: f"Failed to stat AGENT_HUB_SHARED_ROOT={path!r}: {exc}",
            error_factory=_error_factory,
        )
