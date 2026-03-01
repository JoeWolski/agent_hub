# Validation Report: Ground-Up Architecture Overhaul

## Scope
This implementation cycle delivers:
- AOH-01: shared core helper extraction and duplication removal in CLI/Hub.
- AOH-02 foundation: typed canonical runtime config model/loader with startup fail-fast parsing.

## Implemented Changes
- Added `src/agent_core/` package with:
  - `errors.py` typed error classes
  - `shared.py` shared helper functions used by CLI/Hub
  - `config/__init__.py` typed `AgentRuntimeConfig` loader and validators
- Updated `src/agent_cli/cli.py` to:
  - delegate duplicated helper logic to `agent_core.shared`
  - validate parsed runtime config at startup (`ConfigError` -> `ClickException`)
- Updated `src/agent_hub/server.py` to:
  - delegate duplicated helper logic to `agent_core.shared`
  - validate parsed runtime config at startup (`ConfigError` -> `ClickException`)
- Updated packaging in `pyproject.toml` to include `src/agent_core`.
- Added tests:
  - `tests/test_agent_core_shared.py`
  - `tests/test_agent_core_config.py`

## Validation Evidence
See `validation/manifest.txt`.

Key passing evidence:
- Shared/config unit tests: PASS (`14 passed`).
- Hub+CLI targeted config/identity/runtime tests: PASS (`54 passed`).
- Additional config/settings and runtime-config subsets: PASS.

Known contract gap:
- Selector `prepare_agent_cli_command or launch_profile` currently matches no tests (`exit 5`, all deselected).

## Acceptance Mapping
- AOH-01: Mostly satisfied (shared helper extraction and wiring complete; one stale selector in required command set).
- AOH-02: Foundation delivered (typed config loader and fail-fast parse checks), but not yet complete SSOT migration.
- AOH-03/AOH-04/AOH-05: not implemented in this cycle.

## Result
Implementation is stable for delivered scope (AOH-01 + AOH-02 foundation) with passing targeted regressions, and documented remaining work for full overhaul completion.
