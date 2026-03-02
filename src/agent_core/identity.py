from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .config import AgentRuntimeConfig
from . import shared as core_shared

_RUNTIME_IDENTITY_UID_KEYS = ("uid",)
_RUNTIME_IDENTITY_GID_KEYS = ("gid",)
_RUNTIME_IDENTITY_USERNAME_KEYS = ("username",)
_RUNTIME_IDENTITY_SUPPLEMENTARY_GIDS_KEYS = ("supplementary_gids",)
_RUNTIME_IDENTITY_SHARED_ROOT_KEYS = ("shared_root",)


@dataclass(frozen=True)
class RuntimeIdentityConfig:
    uid_raw: str = ""
    gid_raw: str = ""
    username: str = ""
    supplementary_gids: str = ""
    shared_root: str = ""


@dataclass(frozen=True)
class RuntimeIdentity:
    username: str
    uid: int
    gid: int
    supplementary_gids: str = ""
    umask: str = "0022"


def _config_value_by_keys(values: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values:
            return values.get(key)
    return None


def parse_non_negative_int_value(raw_value: Any, *, source_name: str, error_factory: Callable[[str], Exception]) -> int:
    raw = str(raw_value or "").strip()
    if not raw:
        raise error_factory(f"Invalid {source_name}: expected non-negative integer, got {raw!r}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise error_factory(f"Invalid {source_name}: expected non-negative integer, got {raw!r}") from exc
    if value < 0:
        raise error_factory(f"Invalid {source_name}: expected non-negative integer, got {raw!r}")
    return value


def parse_runtime_identity_config(runtime_config: AgentRuntimeConfig | None) -> RuntimeIdentityConfig:
    if runtime_config is None:
        return RuntimeIdentityConfig()
    identity_values = runtime_config.identity.values
    if not isinstance(identity_values, dict):
        return RuntimeIdentityConfig()
    return RuntimeIdentityConfig(
        uid_raw=str(_config_value_by_keys(identity_values, *_RUNTIME_IDENTITY_UID_KEYS) or "").strip(),
        gid_raw=str(_config_value_by_keys(identity_values, *_RUNTIME_IDENTITY_GID_KEYS) or "").strip(),
        username=str(_config_value_by_keys(identity_values, *_RUNTIME_IDENTITY_USERNAME_KEYS) or "").strip(),
        supplementary_gids=core_shared.normalize_csv(
            str(
                _config_value_by_keys(
                    identity_values,
                    *_RUNTIME_IDENTITY_SUPPLEMENTARY_GIDS_KEYS,
                )
                or ""
            )
        ),
        shared_root=str(_config_value_by_keys(identity_values, *_RUNTIME_IDENTITY_SHARED_ROOT_KEYS) or "").strip(),
    )


def parse_configured_uid_gid(
    identity_config: RuntimeIdentityConfig,
    *,
    error_factory: Callable[[str], Exception],
) -> tuple[int | None, int | None]:
    uid_raw = identity_config.uid_raw
    gid_raw = identity_config.gid_raw
    if not uid_raw and not gid_raw:
        return None, None
    if not uid_raw or not gid_raw:
        raise error_factory("identity.uid and identity.gid must be set together when configured.")
    uid = parse_non_negative_int_value(uid_raw, source_name="identity.uid", error_factory=error_factory)
    gid = parse_non_negative_int_value(gid_raw, source_name="identity.gid", error_factory=error_factory)
    return uid, gid
