from __future__ import annotations

import os
import pwd
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import AgentRuntimeConfig
from .errors import IdentityError
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


@dataclass(frozen=True)
class RuntimeIdentityResolverContract:
    username_candidates: tuple[str, ...] = ()
    uid_for_username: int = 0
    explicit_supplementary_gids: str | None = None
    configured_supplementary_gids: str = ""
    default_supplementary_gids: str = ""


@dataclass(frozen=True)
class RuntimeIdentityResolutionContract:
    runtime_config: AgentRuntimeConfig | None = None
    explicit_uid: int | None = None
    explicit_gid: int | None = None
    explicit_username: str = ""
    explicit_supplementary_gids: str | None = None
    override_uid_raw: str = ""
    override_gid_raw: str = ""
    override_username: str = ""
    override_supplementary_gids: str | None = None
    override_uid_source_name: str = "uid"
    override_gid_source_name: str = "gid"
    override_uid_gid_pair_message: str = "uid and gid must be set together."
    shared_root_candidates: tuple[str, ...] = ()
    default_uid: int = 0
    default_gid: int = 0
    default_supplementary_gids: str = ""
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


def default_supplementary_gids() -> str:
    gids = sorted({int(gid) for gid in os.getgroups() if int(gid) != int(os.getgid())})
    return ",".join(str(gid) for gid in gids)


def resolve_runtime_supplementary_gids(contract: RuntimeIdentityResolverContract) -> str:
    if contract.explicit_supplementary_gids is not None:
        return core_shared.normalize_csv(contract.explicit_supplementary_gids)
    configured = core_shared.normalize_csv(contract.configured_supplementary_gids)
    if configured:
        return configured
    return core_shared.normalize_csv(contract.default_supplementary_gids)


def resolve_runtime_username(
    contract: RuntimeIdentityResolverContract,
    *,
    username_lookup: Callable[[int], str],
    error_factory: Callable[[str], Exception],
    missing_username_message_factory: Callable[[int], str],
) -> str:
    for candidate in contract.username_candidates:
        username = str(candidate or "").strip()
        if username:
            return username
    try:
        return str(username_lookup(int(contract.uid_for_username))).strip()
    except (KeyError, ValueError) as exc:
        raise error_factory(missing_username_message_factory(int(contract.uid_for_username))) from exc


def resolve_runtime_identity(
    contract: RuntimeIdentityResolutionContract,
    *,
    resolve_username: bool = True,
    username_lookup: Callable[[int], str] | None = None,
    missing_username_message_factory: Callable[[int], str] | None = None,
    stat_lookup: Callable[[str], os.stat_result] | None = None,
    stat_error_message_factory: Callable[[str, OSError], str] | None = None,
    error_factory: Callable[[str], Exception] = IdentityError,
) -> RuntimeIdentity:
    identity_config = parse_runtime_identity_config(contract.runtime_config)
    configured_uid, configured_gid = parse_configured_uid_gid(identity_config, error_factory=error_factory)

    override_uid_raw = str(contract.override_uid_raw or "").strip()
    override_gid_raw = str(contract.override_gid_raw or "").strip()
    has_uid_override = bool(override_uid_raw)
    has_gid_override = bool(override_gid_raw)
    if has_uid_override or has_gid_override:
        if not has_uid_override or not has_gid_override:
            raise error_factory(str(contract.override_uid_gid_pair_message))
        override_uid = parse_non_negative_int_value(
            override_uid_raw,
            source_name=str(contract.override_uid_source_name or "uid"),
            error_factory=error_factory,
        )
        override_gid = parse_non_negative_int_value(
            override_gid_raw,
            source_name=str(contract.override_gid_source_name or "gid"),
            error_factory=error_factory,
        )
    else:
        override_uid = None
        override_gid = None

    selected_source = "defaults"
    selected_uid = int(contract.default_uid)
    selected_gid = int(contract.default_gid)
    if configured_uid is not None and configured_gid is not None:
        selected_source = "configured"
        selected_uid = int(configured_uid)
        selected_gid = int(configured_gid)
    elif override_uid is not None and override_gid is not None:
        selected_source = "override"
        selected_uid = int(override_uid)
        selected_gid = int(override_gid)
    else:
        for candidate in (
            str(identity_config.shared_root or "").strip(),
            *(str(value or "").strip() for value in contract.shared_root_candidates),
        ):
            if not candidate:
                continue
            selected_source = "shared_root"
            lookup = stat_lookup or (lambda raw_path: Path(raw_path).stat())
            try:
                metadata = lookup(candidate)
            except OSError as exc:
                if stat_error_message_factory is not None:
                    message = stat_error_message_factory(candidate, exc)
                else:
                    message = f"Failed to stat shared root {candidate!r}: {exc}"
                raise error_factory(message) from exc
            selected_uid = int(metadata.st_uid)
            selected_gid = int(metadata.st_gid)
            break

    uid = int(contract.explicit_uid) if contract.explicit_uid is not None else int(selected_uid)
    gid = int(contract.explicit_gid) if contract.explicit_gid is not None else int(selected_gid)

    if contract.explicit_supplementary_gids is not None:
        supplementary_gids = resolve_runtime_supplementary_gids(
            RuntimeIdentityResolverContract(explicit_supplementary_gids=contract.explicit_supplementary_gids)
        )
    elif selected_source in {"override", "shared_root"} and contract.override_supplementary_gids is not None:
        supplementary_gids = resolve_runtime_supplementary_gids(
            RuntimeIdentityResolverContract(explicit_supplementary_gids=contract.override_supplementary_gids)
        )
    else:
        supplementary_gids = resolve_runtime_supplementary_gids(
            RuntimeIdentityResolverContract(
                configured_supplementary_gids=identity_config.supplementary_gids,
                default_supplementary_gids=contract.default_supplementary_gids,
            )
        )

    if resolve_username:
        username_resolver = username_lookup or (lambda lookup_uid: pwd.getpwuid(int(lookup_uid)).pw_name)
        missing_username_message = missing_username_message_factory or (
            lambda lookup_uid: f"Unable to resolve host username for uid={lookup_uid}."
        )
        username = resolve_runtime_username(
            RuntimeIdentityResolverContract(
                username_candidates=(
                    str(contract.explicit_username or "").strip(),
                    str(identity_config.username or "").strip(),
                    str(contract.override_username or "").strip(),
                ),
                uid_for_username=int(uid),
            ),
            username_lookup=username_resolver,
            error_factory=error_factory,
            missing_username_message_factory=missing_username_message,
        )
    else:
        username = str(
            contract.explicit_username or identity_config.username or contract.override_username or ""
        ).strip()

    return RuntimeIdentity(
        username=str(username or "").strip(),
        uid=int(uid),
        gid=int(gid),
        supplementary_gids=str(supplementary_gids or "").strip(),
        umask=str(contract.umask or "0022"),
    )
