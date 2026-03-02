# Validation Report: Ground-Up Architecture Overhaul

## Scope
This implementation cycle delivers:
- AOH-02 strict canonical config schema enforcement and startup/runtime consumption.
- AOH-03 runtime identity unification and deterministic mount/path behavior.
- AOH-04 service boundary extraction for settings/auth domains.
- AOH-05 fallback pruning in config/runtime/state execution and API compatibility flows.

## Implemented Changes
- `AgentRuntimeConfig` now enforces required canonical sections (`identity`, `paths`, `providers`, `mcp`, `auth`, `logging`, `runtime`).
- Removed legacy top-level provider default backfill (`model`, `model_provider`, `model_reasoning_effort`).
- CLI now parses runtime config once and uses it for shared prompt context and provider-default flag resolution.
- CLI explicit `--config-file` / `--system-prompt-file` now fail fast when missing (no silent fallback for explicit paths).
- Hub `main` now parses runtime config once and passes it into `HubState`.
- Hub runtime defaults now resolve config-first for log level, runtime identity/username, and default agent model selection.
- CLI runtime identity defaults now resolve config-first when explicit identity flags are absent.
- Runtime mode now uses a strict canonical contract (`docker`/`native`/`auto`) with explicit hard-fail requirement checks.
- Extracted `src/agent_hub/services/settings_service.py` and delegated settings payload/update behavior from `HubState`.
- Extracted `src/agent_hub/services/auth_service.py` and delegated callback forwarding host-selection logic from `HubState`.
- Removed live `codex_args` route fallback and replaced with explicit `agent_args` contract + load-time legacy migration.
- Removed unsupported provider/agent-command fallback behavior and strictified runtime-critical `agent_type` state/input normalization.
- Updated default config and affected unit/integration fixtures to canonical schema shape.

## Validation Evidence
See `validation/manifest.txt`.

Key passing evidence:
- Config + settings + runtime-config regressions: PASS.
- Identity and service-extraction targeted regressions: PASS.
- Hub lifecycle and agent-tools ack integration suites: PASS.
- Chat lifecycle ready + preflight integration tests: PASS.

Integration preflight status in this cycle:
- `uv run python tools/testing/run_integration.py --mode direct-agent-cli --preflight`: PASS (`14 passed`)
- `uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight`: PASS (`18 passed, 16 warnings`)

Environment note:
- `/workspace/tmp` resolved as writable in this run context; ownership/preflight suites completed.

## Required Artifact Coverage
- Schema mapping: `schema_mapping.md`
- Identity checklist: `identity_invariant_checklist.md`
- Mount decision log: `mount_decision_log.md`
- Service boundary map: `service_boundary_map.md`
- Fallback decision record: `fallback_decision_record.md`
- Deleted env/flag inventory: `deleted_env_flag_inventory.md`
- Deleted code inventory: `deleted_code_inventory.md`

## Acceptance Mapping
- AOH-02: significantly advanced; strict schema validation and key runtime consumers migrated, full SSOT migration still pending.
- AOH-03: complete for current cycle scope.
- AOH-04: complete for current cycle scope.
- AOH-05: complete for current cycle scope.

## Result
Implementation is stable for delivered scope with full required regressions and integration/preflight suites passing.
