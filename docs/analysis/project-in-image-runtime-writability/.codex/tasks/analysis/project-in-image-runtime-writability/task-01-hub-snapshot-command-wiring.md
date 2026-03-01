# Task 01: Hub Snapshot Command Wiring

Status: COMPLETE

## Objective
Ensure project snapshot build invocations use explicit in-image workspace semantics so ownership repair is guaranteed to run during snapshot preparation.

## Allowed Edit Paths
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/project-in-image-runtime-writability/*`

## Changes Implemented
- Updated `project_snapshot_launch_profile` to pass `project_in_image=True` when `prepare_snapshot_only=True`.
- Updated `_ensure_project_setup_snapshot` to pass `project_in_image=True` when `prepare_snapshot_only=True`.
- Updated unit test coverage to assert `--project-in-image` is present in snapshot build command.

## Commands Run
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "project_snapshot_launch_profile or ensure_project_setup_snapshot" -q` (PASS)
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "ensure_project_setup_snapshot_builds_once" -q` (PASS via grouped run)

## Pass/Fail
PASS

## Remaining Risks
- Full end-to-end integration for daemon/runtime writability remains a follow-up opportunity.
