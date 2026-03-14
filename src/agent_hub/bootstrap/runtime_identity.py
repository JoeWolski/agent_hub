from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_core import AgentRuntimeConfig
from agent_core import identity as core_identity


@dataclass(frozen=True)
class RuntimeIdentityBootstrap:
    runtime_config: AgentRuntimeConfig
    runtime_identity_overrides: Any
    local_uid: int
    local_gid: int
    local_supp_gids: str
    local_user: str
    local_umask: str
    runtime_identity: core_identity.RuntimeIdentity


def resolve_runtime_identity_bootstrap(
    *,
    config_file: Path,
    runtime_config: AgentRuntimeConfig | None,
    runtime_identity_overrides: Any | None,
    load_runtime_config: Callable[[Path], AgentRuntimeConfig],
    runtime_identity_env_overrides_factory: Callable[[], Any],
    empty_runtime_identity_overrides_factory: Callable[[], Any],
    validate_runtime_run_mode: Callable[[AgentRuntimeConfig | None], None],
    default_supplementary_gids_factory: Callable[[], str],
    host_uid_env: str,
    host_gid_env: str,
    host_user_env: str,
    shared_root_env: str,
    identity_error_factory: Callable[[str], Exception],
) -> RuntimeIdentityBootstrap:
    runtime_config_supplied = runtime_config is not None
    if runtime_config is None:
        runtime_config = load_runtime_config(config_file)
    assert runtime_config is not None

    if runtime_identity_overrides is not None:
        resolved_overrides = runtime_identity_overrides
    elif not runtime_config_supplied:
        resolved_overrides = runtime_identity_env_overrides_factory()
    else:
        resolved_overrides = empty_runtime_identity_overrides_factory()

    validate_runtime_run_mode(runtime_config)

    override_supplementary_gids = str(getattr(resolved_overrides, "supplementary_gids", "") or "")
    default_supplementary_gids = (
        default_supplementary_gids_factory() if not override_supplementary_gids else override_supplementary_gids
    )
    resolved_identity = core_identity.resolve_runtime_identity(
        core_identity.RuntimeIdentityResolutionContract(
            runtime_config=runtime_config,
            override_uid_raw=str(getattr(resolved_overrides, "uid_raw", "") or ""),
            override_gid_raw=str(getattr(resolved_overrides, "gid_raw", "") or ""),
            override_username=str(getattr(resolved_overrides, "username", "") or ""),
            override_supplementary_gids=override_supplementary_gids,
            override_uid_source_name=host_uid_env,
            override_gid_source_name=host_gid_env,
            override_uid_gid_pair_message=f"{host_uid_env} and {host_gid_env} must be set together.",
            shared_root_candidates=(str(getattr(resolved_overrides, "shared_root", "") or ""),),
            default_uid=os.getuid(),
            default_gid=os.getgid(),
            default_supplementary_gids=default_supplementary_gids,
        ),
        missing_username_message_factory=(
            lambda lookup_uid: (
                "Host username resolution failed for runtime identity "
                f"(uid={lookup_uid}). Set {host_user_env}."
            )
        ),
        stat_error_message_factory=(
            lambda shared_root, exc: f"Failed to stat {shared_root_env}={shared_root!r}: {exc}"
        ),
        error_factory=identity_error_factory,
    )

    local_uid = int(resolved_identity.uid)
    local_gid = int(resolved_identity.gid)
    local_supp_gids = resolved_identity.supplementary_gids
    local_user = resolved_identity.username
    local_umask = "0022"

    return RuntimeIdentityBootstrap(
        runtime_config=runtime_config,
        runtime_identity_overrides=resolved_overrides,
        local_uid=local_uid,
        local_gid=local_gid,
        local_supp_gids=local_supp_gids,
        local_user=local_user,
        local_umask=local_umask,
        runtime_identity=core_identity.RuntimeIdentity(
            username=local_user,
            uid=local_uid,
            gid=local_gid,
            supplementary_gids=local_supp_gids,
            umask=local_umask,
        ),
    )

