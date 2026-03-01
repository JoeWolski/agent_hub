# Task 01: Hub Snapshot Command Wiring

Status: PLANNED

## Objective
Ensure project snapshot build invocations use explicit in-image workspace semantics so ownership repair is guaranteed to run during snapshot preparation.

## Allowed Edit Paths
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/project-in-image-runtime-writability/*`

## Proposed Changes
- Update project snapshot build command construction to pass the in-image workspace mode used by chat launches.
- Add/adjust tests asserting snapshot build command includes the required mode and remains backward compatible for non-snapshot flows.

## Incremental Testing Breakdown
1. Baseline targeted tests around snapshot command construction.
2. Re-run smallest affected unit test after command wiring edits.
3. Re-run broader `tests/test_hub_and_cli.py` subset covering snapshot launch profile.
4. Run full required validation command list before handoff.

## Required Validation Commands
- `uv run pytest tests/test_hub_and_cli.py -k "snapshot and launch_profile" -q`
- `uv run pytest tests/test_hub_and_cli.py -k "project_in_image" -q`

## Logging/Diagnostics Plan
- Capture generated command arrays and assert flags directly in tests.
- On failure, include full command diff in assertion message.

## PR Evidence Plan
- Add command-level evidence lines in `validation/manifest.txt` for each required test.
- No visual evidence required.

## Risks
- Passing new mode in unintended contexts could alter existing snapshot-only scenarios.
- Mitigation: strict tests for non-project-in-image command paths.
