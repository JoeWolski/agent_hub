# Task Contract: AOH-02

## Title
Implement one canonical runtime configuration contract

## Objective
Define and enforce a typed `AgentRuntimeConfig` schema that is the single source for identity defaults, path strategy, providers, auth endpoints, MCP settings, and logging controls.

## Out of Scope
- UI config editor redesign

## Allowed Edit Paths
- src/agent_core/config/
- src/agent_cli/
- src/agent_hub/
- config/
- tests/

## Assumptions
- startup should fail on invalid required config.
- env vars can be reduced to startup overrides only.

## Required Tests
- Unit: config parse/validation/migration
- Integration: startup with canonical config in DIND and non-DIND
- Regression: preserve zero-arg run behavior

## Required Validation Commands
```bash
uv run pytest tests/test_hub_and_cli.py -k "config or settings_payload" -q
uv run pytest tests/test_hub_and_cli.py -k "prepare_chat_runtime_config" -q
```

## PR Evidence Plan
- Required artifacts:
  - schema spec
  - env/flag to config mapping table
  - implementation artifact: `docs/analysis/ground-up-architecture-overhaul/schema_mapping.md`
- Visualization design:
  - none required
- Self-review gate:
  - no duplicated config source for same field remains

## Incremental Testing Breakdown
- Baseline: capture current config resolution behavior.
- Compile/Smoke: load canonical config in isolated unit tests.
- Chunk Validation: validate each schema section migration.
- Integration Validation: run startup/config runtime tests.
- Final Validation: run required commands.
- Diagnostics Discipline:
  - include field-level validation errors with paths.

## Logging and Diagnostics Plan
- config loader emits one structured startup summary and one structured error on failure.

## Acceptance Criteria
- [x] Every runtime field resolves from canonical config (with explicit overrides).
- [x] Invalid config fails startup deterministically.

## Status
Status: COMPLETE

## Execution Log
```text
command: uv run pytest tests/test_agent_core_config.py -q
result: 5 passed in 0.01s
notes: strict required-section validation + legacy provider-backfill removal validated

command: uv run pytest tests/test_hub_and_cli.py -k "config or settings_payload" -q
result: 49 passed, 280 deselected
notes: startup/config payload behavior stable after strict canonical config adoption

command: uv run pytest tests/test_hub_and_cli.py -k "prepare_chat_runtime_config" -q
result: 3 passed, 326 deselected
notes: runtime config materialization remains stable with strict schema

command: uv run --python 3.13 -m pytest tests/test_hub_and_cli.py -k "config or settings_payload" -q
result: 54 passed, 290 deselected, 10 warnings
notes: startup/config payload behavior remains stable after config-first runtime identity and strict agent-type handling

command: uv run --python 3.13 -m pytest tests/test_hub_and_cli.py -k "prepare_chat_runtime_config" -q
result: 3 passed, 341 deselected
notes: runtime config materialization remains stable after strict fallback pruning
```
