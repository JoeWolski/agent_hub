# Task Contract: AOH-05

## Title
Remove non-essential fallback branches, dead code, and unused env/tests

## Objective
Eliminate legacy compatibility branches and fallback code outside approved DIND exceptions; remove unused env vars/tests/checks and duplicated validations.

## Out of Scope
- changing accepted DIND path/network exception behavior

## Allowed Edit Paths
- src/
- tests/
- docs/

## Assumptions
- one-time migration can handle legacy state conversion.

## Required Tests
- Unit: explicit failure mode tests for removed fallback paths
- Integration: full mode suites (direct-agent-cli + hub-api-e2e)
- Regression: startup/readiness/callback/artifact and credential flows

## Required Validation Commands
```bash
uv run pytest tests/test_hub_and_cli.py -q
uv run python tools/testing/run_integration.py --mode direct-agent-cli --preflight
uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight
```

## PR Evidence Plan
- Required artifacts:
  - deleted-code inventory
  - removed env var/flag inventory
  - fallback branch decision record (kept vs removed)
  - implementation artifacts:
    - `docs/analysis/ground-up-architecture-overhaul/deleted_code_inventory.md`
    - `docs/analysis/ground-up-architecture-overhaul/deleted_env_flag_inventory.md`
    - `docs/analysis/ground-up-architecture-overhaul/fallback_decision_record.md`
- Visualization design:
  - none required
- Self-review gate:
  - every remaining branch condition is either domain logic or approved DIND exception

## Incremental Testing Breakdown
- Baseline: snapshot fallback/legacy branch inventory.
- Compile/Smoke: remove one fallback class at a time with targeted tests.
- Chunk Validation: run domain tests after each removal chunk.
- Integration Validation: run selected integration mode suites.
- Final Validation: run required commands.
- Diagnostics Discipline:
  - every removed fallback has a replacement explicit error condition and message.

## Logging and Diagnostics Plan
- emit warning-level logs once for hard migration actions; normal runtime stays info/debug controlled.

## Acceptance Criteria
- [x] no unused env vars/code/tests remain in scope modules.
- [x] fallback branches are reduced to approved DIND exceptions.

## Status
Status: COMPLETE

## Execution Log
```text
command: uv run pytest tests/test_hub_and_cli.py -k "config or settings_payload" -q
result: 51 passed, 281 deselected, 10 warnings
notes: validated fallback pruning around config parsing/path handling, settings flows, and stricter route contracts

command: uv run pytest tests/test_hub_and_cli.py -q
result: 332 passed, 47 warnings, 3 subtests passed
notes: full hub/cli regression suite remains stable after callback-host pruning + codex_args compatibility removal

command: uv run python tools/testing/run_integration.py --mode direct-agent-cli --preflight
result: 14 passed in 3.02s
notes: integration mode preflight + selected direct-agent-cli suites pass

command: uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight
result: 18 passed, 16 warnings in 8.84s
notes: integration mode preflight + selected hub-api-e2e suites pass

command: uv run --python 3.13 -m pytest tests/test_hub_and_cli.py -q
result: 344 passed, 46 warnings, 3 subtests passed in 23.08s
notes: full regression stable after additional strict state/input fallback pruning

command: uv run python tools/testing/run_integration.py --mode direct-agent-cli --preflight
result: 14 passed in 3.10s
notes: direct mode integration preflight and selected suites pass

command: uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight
result: 18 passed, 16 warnings in 8.74s
notes: hub api mode integration preflight and selected suites pass
```
