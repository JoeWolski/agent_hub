# Project Chat Start Launchability Precheck

## Status

SPEC COMPLETE

## Goal

Prevent `/api/projects/{project_id}/chats/start` from creating a stopped gray chat record when the project state says `build_status=ready` but the snapshot image is not actually launchable. The route must fail before chat creation, and stale ready projects must reconcile back to `pending` so rebuild can resume.

## Non-Goals

- Do not redesign frontend pending or failed chat rendering.
- Do not change direct `/api/chats/{chat_id}/start` semantics beyond existing snapshot checks.
- Do not change project snapshot tag computation or Docker image build behavior.

## Scope

- Add a project-start preflight that uses the same snapshot-ready criteria as runtime launch.
- Reconcile stale `ready` projects back to `pending` inline when preflight detects the snapshot is not launchable.
- Ensure no new chat record is created before that preflight passes.
- Add focused backend regressions for the stale-ready path and the successful path.

## User Stories

- As a user opening a second chat, I should either get a real chat start or a clear `409`, never a dead gray chat that was created and then failed to start.
- As a developer, I need stale `ready` project state to self-heal into a rebuild instead of persisting until a later `/api/state` reconciliation.

## Acceptance Criteria

- `ProjectService.create_and_start_chat(...)` must reject project-level chat creation when the project snapshot is not launchable under the same conditions enforced by `RuntimeService.start_chat(...)`.
- When the project `build_status` is not `ready`, the existing `409 Project image is still being built...` response remains unchanged.
- When the project `build_status` is `ready` but the expected snapshot tag does not match, or the Docker image does not exist, project-level chat creation must:
  - not call `create_chat(...)`
  - not call `start_chat(...)`
  - reset the project to `build_status=pending`
  - clear `setup_snapshot_image`, `snapshot_updated_at`, `build_started_at`, `build_finished_at`, and `build_error`
  - persist the reconciled project state
  - schedule a project rebuild
  - raise `HTTPException(status_code=409, detail="Project image is not ready yet. Wait for setup build to finish.")`
- If a duplicate `request_id` already maps to a `running` or `starting` chat, that existing chat is still returned without performing the new-project preflight.
- If a duplicate `request_id` maps to a `failed` or `stopped` chat, the preflight must run before retrying `start_chat(...)`.
- `_chat_create_lock` must not remain held across the slow `start_chat(...)` call. The lock only protects request-id lookup/reuse, launchability preflight, and optional `create_chat(...)`.

## Class Inventory

- `LaunchProfileService`
  - `chat_snapshot_ready(self, project: dict[str, Any]) -> tuple[bool, str]`
- `ProjectService`
  - `_assert_project_chat_launch_ready(self, *, state: dict[str, Any], project_id: str, project: dict[str, Any]) -> None`
  - `_reconcile_stale_ready_project_for_chat_start(self, *, state: dict[str, Any], project_id: str, project: dict[str, Any]) -> None`
  - `create_and_start_chat(...) -> dict[str, Any]`

## Interfaces And Data

- `LaunchProfileService.chat_snapshot_ready(...)` exposes the existing snapshot-ready predicate without raising:
  - `build_status == "ready"`
  - `setup_snapshot_image` is non-empty
  - `setup_snapshot_image == _project_setup_snapshot_tag(project)`
  - `_docker_image_exists(setup_snapshot_image)` is true
- `ProjectService._assert_project_chat_launch_ready(...)`
  - must be called while `_chat_create_lock` is held
  - may save state and schedule a rebuild when reconciling stale ready projects
  - must not create or mutate chat records
- Reconciliation must mirror the existing ready-to-pending repair semantics already used by startup state refresh.

## Error Model

- Not-ready projects continue to raise `409` with the existing “still being built” detail.
- Stale-ready projects raise `409` with the existing runtime-launch detail after reconciliation.
- Duplicate running/starting request-id reuse remains non-error and bypasses the new preflight.

## Concurrency Model

- `_chat_create_lock` continues to serialize project-level chat creation and request-id reuse.
- Reconciliation happens inside that lock so no chat can be created from stale-ready project state in the same critical section.
- Scheduling a rebuild remains asynchronous and may happen after the `409` has been returned.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/services/launch_profile_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/launch_profile_service.py)
  - [`src/agent_hub/services/project_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/project_service.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Keep the patch backend-only and narrow.
- Do not rely on `/api/state` reconciliation to repair this path after a gray chat has already been created.

## Verification Plan

- No repo-local `./make.sh` wrapper is present in this checkout. Use focused pytest commands.
- Run each new regression in isolation and confirm each completes in under 1 second:
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_create_and_start_chat_reconciles_stale_ready_project_before_creating_chat`
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_create_and_start_chat_reconciles_stale_ready_project_before_retrying_existing_request_id_chat`
- Run the focused slice:
  - `uv run python -m pytest tests/test_hub_and_cli.py -k "create_and_start_chat_rejects_when_project_build_is_not_ready or create_and_start_chat_reconciles_stale_ready_project_before_creating_chat or create_and_start_chat_reconciles_stale_ready_project_before_retrying_existing_request_id_chat or create_and_start_chat_passes_agent_args or create_and_start_chat_retries_existing_failed_request_id_chat or create_and_start_chat_retries_existing_stopped_request_id_chat"`

## PR Evidence Plan

- No UI evidence required because this is a backend-only lifecycle fix.

## Ambiguity Register

- “Project image is not ready” in this feature means launchability under the runtime snapshot predicate, not just persisted `build_status`.
- Reconciliation intentionally happens before chat creation so the failed-start gray chat symptom disappears instead of being repaired after the fact.
