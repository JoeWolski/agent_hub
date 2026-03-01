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
- [ ] no unused env vars/code/tests remain in scope modules.
- [ ] fallback branches are reduced to approved DIND exceptions.

## Status
Status: TODO

## Execution Log
```text
command: pending
result: pending
notes: pending
```

## Remaining Risks
- hidden dependence on historical fallback behavior in external user setups.

