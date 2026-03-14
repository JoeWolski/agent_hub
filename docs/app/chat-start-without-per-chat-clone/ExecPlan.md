# Chat Start Without Per-Chat Clone

## Status

SPEC COMPLETE

## Goal

Make a new chat start directly from the already-built project snapshot and shared project workspace instead of cloning and syncing the repository into a per-chat host workspace on every launch. A ready project build should let new chats go straight to container startup.

## Non-Goals

- Do not redesign project build scheduling or snapshot invalidation.
- Do not remove existing chat workspace fields or chat clone recovery helpers.
- Do not change runtime artifact/tmp directories that are still chat-specific.

## Scope

- Remove the normal per-chat clone/sync step from chat launch preparation.
- Reuse the existing project workspace that project build already clones and syncs.
- Update launch-profile and runtime command tests to prove chat start no longer clones when a project workspace is available.
- Update stale fallback UI copy that still claims there is one cloned directory per chat.

## User Stories

- As a user starting a new chat on a project whose build is already `ready`, startup should just launch the container instead of recloning the repo.
- As a developer inspecting launch profiles, I should see chat start reuse project-level workspace inputs rather than chat clone paths.

## Acceptance Criteria

- `LaunchProfileService._chat_launch_workspace(...)` must treat the shared project workspace as reusable only when `self._state.project_workdir(project["id"])` is an existing directory containing a `.git` directory.
- If `project_workdir(project["id"])` is missing, is not a directory, or exists without `.git/`, chat launch must fall back to `self._state._ensure_chat_clone(chat, project)`.
- When the shared project workspace passes the validity check above, chat start and chat launch profile generation must not call `_ensure_chat_clone(...)`.
- `LaunchProfileService.prepare_chat_launch_context(...)` must never call `_sync_checkout_to_remote(...)`, regardless of whether it uses the project workspace or the fallback chat clone path.
- `chat_start` and `chat_launch_profile` must pass the exact host workspace returned by `_chat_launch_workspace(...)` as the second `--project` argument consumed by `agent_cli`; for ready-project launches this is the shared project workspace path.
- Snapshot-backed new chats must still launch with `project_in_image=True`.
- Existing project build flow remains the only normal-path clone/sync entrypoint; chat-level clone is compatibility fallback only.
- Persisted `chat.workspace` metadata must remain chat-scoped and must not be repointed to the shared project workspace.
- Chat creation must continue to materialize a chat-scoped host workspace directory for artifact upload/staging APIs even when launch command preparation reuses the shared project checkout.
- The fallback/server-rendered UI copy must no longer claim that deleting a project removes “stored clones” or that each chat has its own cloned repo.

## Class Inventory

- `agent_hub.services.launch_profile_service.LaunchProfileService`
  - `_chat_launch_workspace(self, *, chat: dict[str, Any], project: dict[str, Any]) -> Path`
    - Invariant: returns a path suitable for launch preparation under the validity rules in `Interfaces And Data`.
    - Side effects: may create/recover a chat clone only through `_ensure_chat_clone(...)` fallback.
    - Must not sync, fetch, or mutate persisted state directly.
  - `prepare_chat_launch_context(self, *, chat_id: str, chat: dict[str, Any], project: dict[str, Any], resume: bool, agent_tools_token: str, artifact_publish_token: str, ready_ack_guid: str, context_key: str) -> dict[str, Any]`
    - Invariant: uses `_chat_launch_workspace(...)` exactly once to choose the host workspace.
    - Returned dict must continue to include `workspace`, `runtime_config_file`, `container_project_name`, `container_workspace`, `agent_type`, `snapshot_tag`, `project_id`, and `command`.
  - `chat_launch_profile(self, chat_id: str, *, resume: bool = False, agent_tools_token: str = "agent-tools-token", artifact_publish_token: str = "artifact-token", ready_ack_guid: str = "ready-ack-guid") -> dict[str, Any]`
    - Invariant: delegates workspace selection through `prepare_chat_launch_context(...)` so launch profile behavior matches real chat start.
- `agent_hub.services.chat_service.ChatService`
  - `create_chat(...) -> dict[str, Any]`
    - Invariant: persists `chat["workspace"]` as chat-scoped metadata, not the shared project checkout path.
    - Side effects: materializes the chat workspace directory for artifact upload/staging before returning.
- `agent_hub.server_hubstate_runtime_mixin.HubStateRuntimeMixin`
  - fallback HTML copy in the server-rendered shell

## Interfaces And Data

- `LaunchProfileService._chat_launch_workspace(...)`
  - Resolve `project_id = str(project.get("id") or "").strip()`.
  - If `project_id` is non-empty, inspect `self._state.project_workdir(project_id)`.
  - Return that path only if it is a directory and `(path / ".git").is_dir()` is true.
  - Otherwise call and return `self._state._ensure_chat_clone(chat, project)`.
  - This method must not mutate persisted chat/project state.
  - Must not call `_sync_checkout_to_remote(...)`.
- `LaunchProfileService.prepare_chat_launch_context(...)`
  - Use `_chat_launch_workspace(...)` for the `workspace` passed into `_prepare_agent_cli_command(...)`.
  - Keep `project_in_image=True`, runtime tmp mount wiring, and trusted container path logic unchanged.
- `chat_launch_profile(...)`
  - Must observe the same workspace selection logic as real chat start because it calls `prepare_chat_launch_context(...)`.
- `ChatService.create_chat(...)`
  - Continue to persist `chat["workspace"]` as a per-chat host path under `self._state.chat_dir`.
  - Must create that directory with `mkdir(parents=True, exist_ok=True)` so artifact submit/publish staging can succeed without a per-chat git clone.
  - Must not point `chat["workspace"]` at `project_workdir(project_id)`.

## Error Model

- Ready project builds continue to fail fast if the snapshot is not ready.
- An invalid shared workspace candidate (missing path, non-directory path, or directory without `.git/`) is not considered launchable state; it must trigger compatibility fallback clone instead of attempting to launch from that path.
- If the shared project workspace is unexpectedly missing and fallback clone also fails, the existing clone/start failure behavior remains unchanged.

## Concurrency Model

- No new concurrency primitives.
- Multiple chat launches may reuse the same project workspace path concurrently for read-only command preparation and project-base path resolution; no runtime or artifact API may assume that shared checkout is chat-private.
- Project build may continue to mutate the shared checkout during clone/sync, but chat launch in this feature only reads that path for command assembly and base path lookup.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/services/launch_profile_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/launch_profile_service.py)
  - [`src/agent_hub/services/chat_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/chat_service.py)
  - [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Add regression coverage that:
  - asserts `create_chat(...)` materializes a chat-scoped workspace directory and does not repoint persisted `chat["workspace"]` to the shared project workspace
  - asserts `start_chat(...)` uses `project_workdir(project["id"])` when that path is a git workspace and does not call `_ensure_chat_clone(...)` or `_sync_checkout_to_remote(...)`
  - asserts `chat_launch_profile(...)` uses the same project workspace and does not call `_ensure_chat_clone(...)` or `_sync_checkout_to_remote(...)`
  - asserts `start_chat(...)` falls back to `_ensure_chat_clone(...)` when the project workspace path is missing
  - asserts `chat_launch_profile(...)` falls back to `_ensure_chat_clone(...)` when the project workspace path is missing
  - asserts a project workspace candidate that exists but is not a git workspace also triggers fallback clone instead of being used directly
  - asserts the generated command still omits unrelated preflight flags on the ready-project path
  - adds a server-rendered UI regression test for the delete-project/fallback copy so it no longer mentions “stored clones”
  - keeps existing `_ensure_chat_clone(...)` unit tests untouched because clone recovery remains supported fallback behavior

## Verification Plan

- No repo-local `./make.sh` wrapper is present in this checkout. Use direct pytest commands.
- Run each new regression in isolation to satisfy the <=1s/test requirement:
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_create_chat_materializes_chat_workspace_for_artifacts`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_start_chat_prefers_project_workspace_without_chat_clone`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_chat_launch_profile_prefers_project_workspace_without_chat_clone`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_start_chat_falls_back_to_chat_clone_when_project_workspace_missing`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_chat_launch_profile_falls_back_to_chat_clone_when_project_workspace_missing`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_start_chat_falls_back_when_project_workspace_is_not_git_checkout`
    - Expected: `1 passed` and elapsed time under `0:01.00`
  - Command: `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_server_rendered_delete_project_copy_no_longer_mentions_stored_clones`
    - Expected: `1 passed` and elapsed time under `0:01.00`
- Then run the focused slice together:
  - Command: `uv run python -m pytest tests/test_hub_and_cli.py -k "create_chat_materializes_chat_workspace_for_artifacts or start_chat_prefers_project_workspace_without_chat_clone or chat_launch_profile_prefers_project_workspace_without_chat_clone or start_chat_falls_back_to_chat_clone_when_project_workspace_missing or chat_launch_profile_falls_back_to_chat_clone_when_project_workspace_missing or start_chat_falls_back_when_project_workspace_is_not_git_checkout or server_rendered_delete_project_copy_no_longer_mentions_stored_clones or ensure_project_setup_snapshot_builds_once or start_chat_builds_cmd_with_mounts_env_and_repo_base_path or start_chat_builds_cmd_with_repo_dockerfile_uses_workspace_context or start_chat_uses_claude_agent_command_when_selected or start_chat_uses_gemini_agent_command_when_selected or start_chat_resume_for_codex_uses_agent_cli_resume_without_explicit_args"`
    - Expected: all selected tests pass with no failures

## PR Evidence Plan

- No UI evidence required because this is backend/runtime behavior only.

## Ambiguity Register

- Requirement clarification: “new chat should just spin up the ready container” means the normal ready-build launch path reuses the shared project git workspace without chat clone or sync. Compatibility fallback is allowed only when the shared workspace is absent or invalid under the explicit validity rules above; fallback is not allowed merely because a chat has a historical `workspace` field.
