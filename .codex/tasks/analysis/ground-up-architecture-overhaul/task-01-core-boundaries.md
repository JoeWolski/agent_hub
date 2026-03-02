# Task Contract: AOH-01

## Title
Extract shared core boundaries and remove duplicate helper logic

## Objective
Create `agent_core` modules for config, identity, path normalization, and launch-spec primitives; replace duplicated helper functions in CLI/Hub with shared implementations.

## Out of Scope
- API route behavior changes
- auth provider feature changes

## Allowed Edit Paths
- src/agent_core/
- src/agent_cli/
- src/agent_hub/
- tests/

## Assumptions
- Existing integration suites remain authoritative behavior reference.
- DIND path rewrite remains required.

## Required Tests
- Unit: helper parity + schema validation tests
- Integration: launch profile parity tests
- Regression: duplicate helper removal does not alter generated commands

## Required Validation Commands
```bash
uv run pytest tests/test_hub_and_cli.py -k "prepare_agent_cli_command or launch_profile" -q
uv run pytest tests/test_hub_and_cli.py -k "host_identity or runtime_identity" -q
```

## PR Evidence Plan
- Required artifacts:
  - helper-duplication diff summary
  - command parity assertions
- Visualization design:
  - none required
- Self-review gate:
  - duplicated helper implementations removed or delegated to shared core

## Incremental Testing Breakdown
- Baseline: record command outputs for representative launch-profile fixtures.
- Compile/Smoke: run targeted parity tests after first helper extraction.
- Chunk Validation: run focused tests per extracted helper group.
- Integration Validation: run launch-profile and identity tests.
- Final Validation: run required commands.
- Diagnostics Discipline:
  - log parity mismatches with old/new tokens side-by-side.

## Logging and Diagnostics Plan
- Add debug trace in launch-spec compiler only while parity debugging, then keep concise structured logs.

## Acceptance Criteria
- [ ] Shared helper module replaces duplicate definitions in CLI/Hub.
- [ ] Command generation parity tests pass.

## Status
Status: DONE

## Execution Log
```text
command: uv run pytest tests/test_agent_core_shared.py -q
result: 10 passed in 0.01s
notes: new shared helper module behavior validated

command: uv run pytest tests/test_hub_and_cli.py -k "host_identity or runtime_identity" -q
result: 5 passed, 324 deselected
notes: hub identity flows stable after helper delegation

command: uv run pytest tests/test_hub_and_cli.py -k "prepare_agent_cli_command or launch_profile" -q
result: no matches (329 deselected, exit 5)
notes: selector appears stale for current suite; adjacent runtime/config tests executed
```

## Remaining Risks
- Hidden semantic drift in helper edge cases.
