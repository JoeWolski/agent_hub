# Chat Start Clone Recovery

## Status

SPEC COMPLETE

## Goal

Make `POST /api/projects/{project_id}/chats/start` recover cleanly when chat startup races or a previous clone attempt left a partial workspace behind, instead of failing with a `git clone ... destination path ... already exists and is not an empty directory` error.

## Non-Goals

- Do not change the frontend chat creation flow.
- Do not redesign request-id idempotency semantics for completed successful chats.
- Do not alter project clone behavior outside chat workspaces.

## Scope

- Harden chat workspace preparation in [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py).
- Harden chat start state transitions in [`src/agent_hub/services/runtime_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/runtime_service.py).
- Refine request-id retry behavior in [`src/agent_hub/services/project_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/project_service.py) for chats that already exist but are not active.
- Add backend regression tests in [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py).

## User Stories

- As a user starting a new chat, I can retry after a failed clone attempt without manually deleting chat directories.
- As a user who accidentally triggers the same chat start twice, I get a stable conflict instead of a corrupted workspace or a clone race.
- As a developer, I can rely on failed clone attempts leaving no partial workspace state behind for the next retry.
- As a user retrying a failed new-chat request with the same `request_id`, I get the existing chat restarted instead of a stale failed record being returned unchanged.

## Acceptance Criteria

- Starting a chat already in `starting` state must fail fast with `409 Chat is already starting.` and must not call clone or process launch again.
- `_ensure_chat_clone(...)` must:
  - Reuse an existing workspace only when it contains a real `.git` directory.
  - Delete an existing non-git workspace before retrying clone.
  - Invoke `git clone` without pre-creating the destination directory.
  - Delete the destination directory if `git clone` fails after creating partial contents.
- Existing request-id idempotency for already-created chats remains unchanged.
- Existing request-id idempotency remains unchanged for chats already in `starting` or `running`.
- Regression tests cover duplicate start rejection and clone-failure cleanup.

## Class Inventory

- `ProjectService.create_and_start_chat(self, project_id: str, *, agent_args: list[str] | None = None, agent_type: str | None = None, request_id: str | None = None) -> dict[str, Any]`
- `RuntimeService.start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]`
- `HubStateRuntimeMixin._ensure_chat_clone(self, chat: dict[str, Any], project: dict[str, Any]) -> Path`

## State Invariants

- Only one active start sequence may own a given `chat_id` at a time.
- A chat in `starting` is treated as busy for direct `start_chat` calls.
- A workspace created by `_ensure_chat_clone(...)` is reusable only when it already contains a `.git` directory.
- A clone attempt that throws must not leave the chat workspace on disk.

## Interfaces And Data

- `RuntimeService.start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]`
  - Wrap the initial state load and `starting` transition in `self._state._runtime_lock`.
  - Guard before the launch path:
    - If normalized status is `running` and PID is alive, keep existing `409`.
    - If normalized status is `starting`, return `HTTPException(status_code=409, detail="Chat is already starting.")`.
  - Persist the transition to `starting` while still under the lock so a second caller sees the busy state.
- `HubStateRuntimeMixin._ensure_chat_clone(self, chat: dict[str, Any], project: dict[str, Any]) -> Path`
  - Workspace source remains `Path(str(chat.get("workspace") or self.chat_dir / chat["id"]))`.
  - Healthy existing clone detection remains `.git` directory presence.
  - Remove `workspace.mkdir(parents=True, exist_ok=True)` before clone.
  - Wrap `_run(["git", "clone", ...])` in `try/except`.
  - On exception:
    - If destination now exists, delete it with `self._delete_path(...)`.
    - Re-raise the original exception unchanged.
- `ProjectService.create_and_start_chat(...)`
  - When `request_id` matches an existing chat:
    - If chat status is `starting` or `running`, return the existing chat unchanged.
    - Otherwise call `self._state.start_chat(existing_chat["id"])` to retry the same chat record.

## Error Model

- Duplicate start request against a chat already transitioning to running is a conflict, not a generic runtime failure.
- Clone failures still surface through the existing `RuntimeCommandError` / `chat_start_failed` path.
- Cleanup failures during rollback continue to surface via the current `_delete_path(...)` `HTTPException` behavior.
- Request-id retries for failed or stopped chats reuse the same chat id and go back through normal `start_chat(...)` behavior.

## Concurrency Model

- `start_chat` must be single-flight per chat id at the service layer by guarding the status read/write with `self._state._runtime_lock` and treating `starting` as an active launch.
- `create_and_start_chat(...)` uses a dedicated `self._state._chat_create_lock` so request-id matching, chat creation, and first launch are serialized.
- Workspace cleanup remains local to the chat workspace path.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/services/runtime_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/runtime_service.py)
  - [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Keep the patch narrow. Do not change route payloads or state schema.

## Verification Plan

- Command: `uv run python -m pytest tests/test_hub_and_cli.py -k "create_and_start_chat_reuses_existing_request_id_chat or create_and_start_chat_reuses_existing_starting_request_id_chat or create_and_start_chat_retries_existing_failed_request_id_chat or create_and_start_chat_retries_existing_stopped_request_id_chat or create_and_start_chat_serializes_duplicate_request_id_calls or ensure_chat_clone_reuses_existing_git_workspace_without_recloning or ensure_chat_clone_recreates_non_git_workspace_before_clone or ensure_chat_clone_removes_partial_clone_workspace or ensure_chat_clone_removes_workspace_when_clone_creates_partial_contents_then_fails or ensure_chat_clone_surfaces_cleanup_failure_with_clone_error_context or start_chat_rejects_duplicate_start_when_chat_is_starting or start_chat_does_not_overwrite_chat_closed_during_launch or start_chat_failure_does_not_overwrite_chat_closed_during_launch or start_chat_stops_process_when_chat_removed_before_completion"`
  - Expected: all selected tests pass.
- Command: `uv run python -m pytest tests/integration/test_hub_chat_lifecycle_api.py`
  - Expected: `7 passed`.

## PR Evidence Plan

- No UI evidence required because this is a backend-only change.

## Ambiguity Register

- Assumption: a workspace with a `.git` directory is sufficiently healthy for current chat-start semantics. Full repository-health validation is out of scope for this fix.
- Assumption: startup reconciliation remains the mechanism for clearing stale persisted `starting` chats after process restart; this fix only handles live duplicate starts.
- Assumption: request-id matching stays scoped to the existing `(project_id, request_id)` behavior; payload-drift conflict handling is out of scope here.
