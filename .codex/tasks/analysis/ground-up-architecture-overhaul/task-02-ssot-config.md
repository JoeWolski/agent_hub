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
- [ ] Every runtime field resolves from canonical config (with explicit overrides).
- [ ] Invalid config fails startup deterministically.

## Status
Status: TODO

## Execution Log
```text
command: pending
result: pending
notes: pending
```

## Remaining Risks
- Backward compatibility pressure from legacy env-based flows.

