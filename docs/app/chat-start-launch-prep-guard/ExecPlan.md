# Chat Start Launch Prep Guard

## Status

SPEC COMPLETE

## Goal

Prevent `/api/state` from marking a chat `failed` while `start_chat(...)` is still preparing the launch context and no PID has been persisted yet. New chats must stay in `starting` until launch prep either fails explicitly or a real runtime process is spawned and recorded.

## Non-Goals

- Do not redesign frontend pending-chat behavior.
- Do not change persisted chat schema or route payloads.
- Do not weaken stale-start cleanup after process restart.

## Scope

- Add live in-memory tracking for chat launches that are actively inside `RuntimeService.start_chat(...)`.
- Teach `AppStateService.state_payload(...)` to skip the `starting -> failed` reconciliation only for chats in that active launch set.
- Add backend regression coverage for the launch-prep race and for stale `starting` chats that are not actively launching.

## User Stories

- As a user starting a new chat, I keep seeing a real startup state while clone/sync work is in progress instead of an immediate failed pane.
- As a developer, I can still rely on stale `starting` chats being repaired to `failed` when no live launch is running.

## Acceptance Criteria

- While `RuntimeService.start_chat(...)` is actively preparing launch context for a chat, `/api/state` must not flip `status=starting` with `pid=None` to `failed`.
- `RuntimeService.start_chat(...)` must register the pending-launch guard while still holding `_runtime_lock`, in the same critical section that persists `status=starting` and `pid=None`, before releasing `_runtime_lock`.
- Once that active launch finishes, the in-memory guard must always clear, whether startup succeeds, fails, the chat is closed, or the chat is removed.
- On the success path, the pending-launch guard must remain set until after `chat_start_succeeded` persists both `status=running` and `pid=<spawned pid>`.
- On failure paths before that success save, the pending-launch guard must remain set until after failure or abort handling has completed and `start_chat(...)` is exiting.
- `AppStateService.state_payload(...)` must continue marking chats `failed` when:
  - `status=running` and the persisted PID is not alive
  - `status=starting` and no active launch guard exists
  - `status=starting` with a dead persisted PID
- `close_chat(...)`, chat deletion, and `/api/state` reconciliation must not clear the pending-launch guard directly; only the owning `start_chat(...)` call clears it.
- If a chat is closed during launch prep, the final persisted status must remain `stopped` with the close-request reason, and later launch cleanup must not overwrite it.
- If a chat is deleted during launch prep, the chat must remain deleted, and later launch cleanup must not recreate or mutate it.
- Existing startup reconciliation on process restart remains unchanged.

## Class Inventory

- `RuntimeDomain`
  - `__init__(...) -> None` adds `_chat_launch_tracking_lock: Lock` and `_chat_launches_in_progress: set[str]`
  - `mark_chat_launch_pending(self, chat_id: str) -> None`
  - `clear_chat_launch_pending(self, chat_id: str) -> None`
  - `is_chat_launch_pending(self, chat_id: str) -> bool`
- `RuntimeService.start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]`
- `AppStateService.state_payload(self) -> dict[str, Any]`

## Interfaces And Data

- `RuntimeDomain` stores an in-memory `set[str]` of chat ids whose launch is actively inside `start_chat(...)` before the final persisted PID/status handoff.
- `mark_chat_launch_pending(...)` and `clear_chat_launch_pending(...)` are idempotent and must not raise for existing or missing entries.
- `is_chat_launch_pending(...)` must be an O(1) locked lookup and must not acquire `_runtime_lock`.
- Code holding the pending-launch lock must never call state load/save, `_close_runtime(...)`, or any path that can acquire `_runtime_lock`.
- `RuntimeService.start_chat(...)`
  - Calls `self._state.runtime_domain.<helper>(...)` directly; do not add new HubState passthrough methods for this feature.
  - Registers the chat in the pending-launch set immediately after the `starting` transition is persisted and before long-running launch prep starts.
  - Uses `resume=True` and normal starts identically for guard lifetime; both paths are protected because both pass through the same launch-prep and spawn handoff.
  - Keeps the guard set through launch prep and the spawned-process handoff, and clears it only when the owning `start_chat(...)` call is exiting after authoritative state or abort cleanup has completed.
- `AppStateService.state_payload(...)`
  - Computes `launch_pending = normalized_status == starting and pid is None and runtime_domain.is_chat_launch_pending(chat_id)`.
  - `launch_pending` is advisory only for the single case above.
  - If `launch_pending` is true, it must:
    - not call `_close_runtime(chat_id)`
    - not transition the chat to `failed`
    - return the persisted lifecycle fields unchanged, aside from existing non-lifecycle normalization already performed in `state_payload(...)`
  - If persisted `pid` is an `int`, the guard must be ignored and the existing dead-PID reconciliation rules stay authoritative.
  - If persisted status is not `starting`, the guard must be ignored.
  - Otherwise the existing `chat_process_not_running_during_state_refresh` failure path stays in force.

## Error Model

- Explicit startup errors from launch prep or process spawn still transition the chat to `failed` through the current `chat_start_failed` path.
- The active launch guard is advisory only; it must never mask a direct failure raised by `start_chat(...)`.

## Concurrency Model

- `_runtime_lock` continues to serialize authoritative status transitions.
- Pending-launch tracking uses its own in-memory lock so `start_chat(...)` can register the guard while already holding `_runtime_lock`.
- Lock ordering is one-way only: code that already holds `_runtime_lock` may call pending-launch helpers; pending-launch helpers must never acquire `_runtime_lock`.
- `state_payload(...)` may race with `start_chat(...)`; the guard makes that race safe without changing persisted schema.
- The design relies on ordering, not timing. There must be no observable interval where persisted state says `starting` with `pid=None` for an accepted launch but the pending-launch guard is absent.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/domains/runtime_domain.py`](/home/joew/projects/agent_hub/src/agent_hub/domains/runtime_domain.py)
  - [`src/agent_hub/services/runtime_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/runtime_service.py)
  - [`src/agent_hub/services/app_state_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/app_state_service.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Keep the patch backend-only and narrow.
- Do not add time-based grace periods; the fix should key off actual in-flight launch ownership.

## Verification Plan

- No repo-local `./make.sh` wrapper is present in this checkout. Use the direct commands below.
- Command: `uv run python -m pytest tests/test_hub_and_cli.py -k "state_payload_marks_finished_running_chat_failed or state_payload_preserves_starting_chat_during_active_launch_prep or state_payload_marks_stale_starting_chat_failed_without_active_launch_guard or state_payload_preserves_starting_chat_during_spawn_to_running_handoff or start_chat_marks_chat_failed_when_launch_prep_raises or start_chat_failure_does_not_overwrite_chat_closed_during_launch or start_chat_stops_process_when_chat_removed_before_completion or start_chat_does_not_overwrite_chat_closed_during_launch"`
  - Expected: all selected tests pass.
- Command: `uv run python -m pytest tests/integration/test_hub_chat_lifecycle_api.py`
  - Expected: all integration tests pass.

## PR Evidence Plan

- No UI evidence required because this is a backend-only lifecycle fix.

## Ambiguity Register

- Requirement: `prepare_chat_launch_context(...)` is the expensive pre-PID phase that must stay protected, and the spawned-process handoff before `chat_start_succeeded` must stay protected too.
- Requirement: stale persisted `starting` chats after process restart must still reconcile to `failed` because the pending-launch set is in-memory only and is empty on restart.
