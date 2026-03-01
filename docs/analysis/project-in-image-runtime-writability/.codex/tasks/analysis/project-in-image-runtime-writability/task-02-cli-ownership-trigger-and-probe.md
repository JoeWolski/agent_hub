# Task 02: CLI Ownership Trigger And Probe

Status: COMPLETE

## Objective
Refactor ownership-repair trigger to depend on deterministic snapshot workspace-copy state and add explicit writability probe before snapshot commit.

## Allowed Edit Paths
- `src/agent_cli/cli.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/project-in-image-runtime-writability/*`

## Changes Implemented
- Added `_verify_snapshot_project_writable` helper.
- Switched repair/probe trigger to `snapshot_workspace_copied_into_image = not use_project_bind_mount`.
- Enforced sequence: setup run -> ownership repair -> writability probe (runtime UID:GID) -> commit.
- Added/updated tests for both `--project-in-image` and `--prepare-snapshot-only` snapshot build paths.

## Commands Run
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "snapshot_runtime_project_in_image_repairs_project_ownership_before_commit or snapshot_prepare_only_repairs_project_ownership_and_verifies_writable_before_commit" -q` (PASS via grouped run)
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable_1772390241/.venv uv run pytest tests/test_hub_and_cli.py -k "snapshot_runtime_project_in_image" -q` (PASS)

## Pass/Fail
PASS

## Remaining Risks
- Broader snapshot test subset includes unrelated pre-existing failures due `/tmp` daemon-visibility checks.
