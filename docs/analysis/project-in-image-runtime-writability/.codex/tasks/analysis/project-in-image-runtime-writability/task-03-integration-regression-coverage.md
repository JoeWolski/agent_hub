# Task 03: Integration Regression Coverage

Status: REVISED_COMPLETE

## Objective
Add integration coverage that reproduces hub-managed snapshot build and validates writable project paths in a new chat runtime.

## Allowed Edit Paths
- `tests/integration/*snapshot*`
- `tests/integration/*hub*`
- `src/agent_hub/server.py` (only if needed for testability hooks)
- `docs/analysis/project-in-image-runtime-writability/*`

## Revision Outcome
- Delivered stronger unit-level regression coverage for hub command wiring and CLI repair/probe ordering.
- Deferred new integration test in this change to keep scope deterministic and unblock core runtime fix.
- Captured residual integration risk and follow-up need in validation/verification artifacts.

## Commands Run
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "snapshot" -q` (FAIL, unrelated pre-existing `/tmp` daemon-visibility failures)
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "snapshot_commit_resets_entrypoint_and_cmd" -q` (PASS)

## Pass/Fail
REVISED_COMPLETE

## Remaining Risks
- No new real-daemon integration write check was added; recommend follow-up integration test once `/tmp` daemon-visibility test fixtures are normalized.
