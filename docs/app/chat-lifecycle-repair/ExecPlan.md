# Chat Lifecycle Repair

## Status

SPEC COMPLETE

## Goal

Repair the new-chat lifecycle so one user click produces exactly one visible chat, the chat row transitions from optimistic to authoritative state without leaving a phantom duplicate behind, and terminal startup failures render as failed instead of getting stuck behind a stale "Starting chat..." UI.

## Problem Summary

The current lifecycle mixes two identities for the same create intent:

- the frontend creates an optimistic row keyed by `pending-*` `ui_id`
- the backend creates the real chat keyed by persisted `chat.id`

That handoff is currently loose:

- the frontend may keep rendering a `pending-*` row after the real chat exists
- fallback matching can attach an optimistic row to the wrong server chat inside the same project
- `pendingChatStarts` can keep a stopped chat rendering as `starting` even after the server has already published a terminal state
- `projectChatCreateLocksRef` and `pendingProjectChatCreates` can stay latched until the POST settles even after `/api/state` has already identified the authoritative chat
- a delayed POST success can still enqueue `pendingChatStarts[chat.id]` after the server has already published `failed` or `stopped`
- overlapping raw `refreshState()` calls can apply snapshots out of order and briefly resurrect stale optimistic state
- the backend guarantees request-id idempotency only when the same `request_id` is reused; it does not yet provide explicit lifecycle metadata for "this create request already resolved to chat X"

The user-visible result matches the reported bug:

- one click can appear to spawn a "good" authoritative chat plus a "bad" phantom chat
- the phantom row/tab can land on a failed/stopped chat record but still look startup-pending
- retry behavior is unclear because frontend optimism and backend request-id reuse are not modeled as one state machine

## Non-Goals

- Do not redesign the overall project/chats page layout.
- Do not change agent launch arguments, snapshot preparation, or container command composition.
- Do not change chat persistence schema beyond narrowly scoped lifecycle metadata required for deterministic create/start reconciliation.
- Do not replace the current websocket/state polling architecture.

## Scope

- Frontend lifecycle reconciliation in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx).
- Frontend pending-state helpers in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js).
- Flex-layout chat-tab identity reconciliation in [`web/src/flexLayoutState.js`](/home/joew/projects/agent_hub/web/src/flexLayoutState.js) if tab ids must be rekeyed from pending ids to server ids.
- API route integration in [`src/agent_hub/api/routes.py`](/home/joew/projects/agent_hub/src/agent_hub/api/routes.py).
- Backend project create/start orchestration in [`src/agent_hub/services/project_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/project_service.py).
- Backend runtime start semantics in [`src/agent_hub/services/runtime_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/runtime_service.py).
- State-payload lifecycle metadata exposure in [`src/agent_hub/services/app_state_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/app_state_service.py) if required.
- Request-id lookup helper behavior in [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py).
- API and integration regression coverage in [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py), [`tests/integration/test_hub_chat_lifecycle_api.py`](/home/joew/projects/agent_hub/tests/integration/test_hub_chat_lifecycle_api.py), [`tests/test_web_pending_state.py`](/home/joew/projects/agent_hub/tests/test_web_pending_state.py), and [`web/src/chatPendingState.test.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.test.js).

## Non-Scope

- Standalone `POST /api/chats` create-without-start flow.
- Title generation, artifact publishing, or terminal websocket reconnect behavior.
- Mobile/capacitor-specific chat wrappers.

## User Stories

- As a user, when I click `New chat`, I see one chat row and one chat tab, not a phantom duplicate.
- As a user, if chat startup fails, the same chat row cleanly transitions to `failed` with the server error; it must not remain visually `starting`.
- As a user, if the browser receives state updates before the create/start HTTP response returns, the UI still attaches the optimistic row to the correct server chat.
- As a user, if the browser retries the same create intent, the backend returns the same chat instead of creating a second record.
- As a developer, I can reason about one create intent as one lifecycle state machine with explicit invariants and regression tests.

## Acceptance Criteria

- One project-level `New chat` click yields exactly one visible chat row and exactly one project chat tab.
- The frontend must never render both `pending-*` and persisted `chat.id` entries for the same create request at the same time after the server chat becomes known.
- If flex layout is active while a pending row is promoted to the authoritative chat id, the selected tab and tab order must remain stable; promotion must not jump focus to a different tab or append a duplicate tab at the end.
- Identity promotion must be order-independent:
  - if `/api/state` shows the authoritative chat before the create/start POST resolves, the pending row still converges to that chat
  - if the create/start POST resolves before `/api/state` includes the authoritative chat, the pending row still converges to that chat
- An exact `create_request_id` match to an authoritative chat in `starting`, `running`, `failed`, or `stopped` must replace the optimistic placeholder immediately; it must not wait for timeout cleanup.
- If the authoritative chat has already been attached from server state, a later client-side POST error must not delete or hide that authoritative chat; it may only clear the transient pending-create state and surface the error.
- If the authoritative chat has already been attached from server state, a later HTTP success is a no-op for identity state.
- Optimistic pending-session matching must be authoritative by `server_chat_id` first, then `create_request_id`; it must not fall back to "any starting/running chat in the same project".
- Once a server chat has been observed, frontend startup rendering must follow server lifecycle state:
  - `status == starting` => render starting
  - `status == running && is_running` => render running
  - `status in {failed, stopped}` with `is_running == false` => do not render starting
- `pendingChatStarts` may only keep a chat visually pending while the chat has not yet been materialized on the server or while the server still reports `starting`; it must not mask `failed` or `stopped`.
- Project-level create locking must clear as soon as a pending session is promoted from `pending-*` to the authoritative `chat.id`; it must not wait for the originating POST promise to settle.
- A stale create/start success handler must not re-mark an already-materialized `failed` or `stopped` authoritative chat as pending-start.
- Create/start-triggered state refreshes must go through `queueStateRefresh()`; the repaired lifecycle must not add new raw overlapping `refreshState()` calls.
- Project create/start idempotency must stay single-flight under `self._state._chat_create_lock`.
- Repeating the same `(project_id, request_id)` must return the same persisted chat record whether it is `starting`, `running`, `failed`, or `stopped`; it must not create a second chat.
- Backend responses and/or state payload must expose enough lifecycle metadata for the frontend to deterministically join an optimistic row to the authoritative server chat without using same-project heuristics.

## Root-Cause Design Decision

Treat `create_request_id` as the canonical join key for chat creation until `server_chat_id` is known, then immediately promote all UI state to the authoritative `chat.id` and delete the pending row identity. The frontend must not infer a match from project membership plus startup-looking status.

The temporary `pending-*` row is allowed only as a render-only placeholder while no authoritative server chat is known yet. It is not a second lifecycle identity, not a second tab identity, and not a second source of truth.

## State Invariants

- One user create intent maps to at most one persisted chat record.
- One persisted chat record maps to at most one visible UI row and one visible project-tab identity.
- `pending-*` ids are transient transport identities only; they must never outlive the point where the corresponding `server_chat_id` is known.
- The server is authoritative once a chat record exists in `/api/state`.
- Terminal states from the server (`failed`, `stopped`) override optimistic startup state immediately.
- Project-level create spinners/locks must clear when the create request is resolved to a specific authoritative chat or ends in a surfaced request error.
- Identity promotion is idempotent: promoting the same `ui_id -> chat.id` mapping more than once must not duplicate rows, tabs, or keyed UI state.
- Reusing the same `(project_id, request_id)` with different `agent_type` or `agent_args` must not mutate the original persisted chat configuration.
- Non-authoritative caches/refs may be rebuilt lazily, but they must never resurrect a promoted `pending-*` identity after promotion has completed.

## Interfaces And Data

### Frontend Data Model

Keep the existing pending-session object but tighten its semantics:

- `ui_id: str`
- `project_id: str`
- `project_name: str`
- `agent_type: str`
- `create_request_id: str`
- `server_chat_id: str`
- `created_at_ms: number`
- `server_chat_id_set_at_ms: number`
- `known_server_chat_ids: string[]`
- `seen_on_server: boolean`

No new persisted backend schema is required for the base fix if `create_request_id` remains included in state payloads.

### Frontend Function Inventory

- `handleCreateChat(projectId, startSettings = null)` in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx)
  - Continue generating a unique `request_id`.
  - After the POST succeeds, call a new local helper to atomically promote UI state from `ui_id` to `chat.id`, but only if that pending session still exists locally.
  - Do not leave the pending session in place after that promotion.
  - If `/api/state` already promoted the session before the POST resolves, treat the POST success as a no-op for identity state and do not enqueue `pendingChatStarts[chat.id]`.
  - In the `catch` path, remove only still-unresolved optimistic state. If a prior state-refresh path already promoted the session to a real `chat.id`, keep the authoritative chat visible.
  - Use `queueStateRefresh()` rather than raw `refreshState()` after create success/error so chat-lifecycle snapshots stay serialized.
- New helper in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx):
  - `promotePendingChatIdentity(uiId: string, serverChatId: string, projectId: string) -> boolean`
  - Responsibilities:
    - remove the matching pending session
    - migrate `openChats`, `openChatDetails`, `openChatLogs`, `pendingChatLogLoads`, `chatStaticLogs`, `showArtifactThumbnailsByChat`, `collapsedTerminalsByChat`, `fullscreenChatId`, and `artifactPreview.chatId` from `ui_id` keys to `server_chat_id`
    - update `chatOrderAliasByServerIdRef`
    - clear `pendingProjectChatCreates[projectId]` and `projectChatCreateLocksRef.current.delete(projectId)` as part of promotion
    - rekey project-flex-layout tabs that still reference the old `pending-*` id while preserving the selected tab and the tab's position within its tabset
  - Must be idempotent and return `true` only when it actually promoted a still-pending local identity.
- New extracted frontend helper module:
  - file: [`web/src/chatIdentityState.js`](/home/joew/projects/agent_hub/web/src/chatIdentityState.js)
  - test file: [`web/src/chatIdentityState.test.js`](/home/joew/projects/agent_hub/web/src/chatIdentityState.test.js)
  - exported function: `rekeyChatUiIdentityState(prev: ChatUiIdentityState, uiId: string, serverChatId: string) -> ChatUiIdentityState`
  - `ChatUiIdentityState` must include:
    - `pendingSessions`
    - `openChats`
    - `openChatDetails`
    - `openChatLogs`
    - `pendingChatLogLoads`
    - `chatStaticLogs`
    - `showArtifactThumbnailsByChat`
    - `collapsedTerminalsByChat`
    - `fullscreenChatId`
    - `artifactPreview`
    - `chatFlexProjectLayoutsByProjectId`
  - `ChatUiIdentityState` explicitly does not include:
    - `chatFlexOuterLayoutJson`
    - `chatFlexOuterModelCacheRef`
    - `chatFlexProjectModelCacheRef`
    - `chatFirstSeenOrderRef`
    - `projectFirstSeenOrderRef`
  - Those excluded refs/caches remain non-authoritative derived state:
    - `chatOrderAliasByServerIdRef` must still be updated by `promotePendingChatIdentity(...)`
    - first-seen ordering is preserved by aliasing and by removing the pending session immediately
    - flex-layout model caches may be invalidated/rebuilt after layout JSON rekey and must not be manually rekeyed
  - `promotePendingChatIdentity(...)` should delegate to this pure helper so the migration logic is directly testable.
  - Rekey semantics are mandatory and must not be invented during implementation:
    - `pendingSessions`: remove the promoted `ui_id` entry entirely; do not leave a second session keyed to `serverChatId`
    - keyed boolean maps (`openChats`, `openChatDetails`, `openChatLogs`, `pendingChatLogLoads`, `showArtifactThumbnailsByChat`, `collapsedTerminalsByChat`): move the `ui_id` value to `serverChatId`, preserve any existing truthy server value, then delete the `ui_id` key
    - `chatStaticLogs`: if both keys exist, preserve the non-empty `serverChatId` value; otherwise move the `ui_id` value
    - `fullscreenChatId`: replace `ui_id` with `serverChatId`
    - `artifactPreview`: if `artifactPreview.chatId === ui_id`, rewrite it to `serverChatId`; otherwise leave it unchanged
    - `chatFlexProjectLayoutsByProjectId`: for the matching project layout only, rekey any `project-chat-pane` tab from `chat-pending-*` / `config.chat_id = pending-*` to the authoritative `chat-${serverChatId}` / `config.chat_id = serverChatId`
    - if multiple pending sessions incorrectly resolve to the same `serverChatId`, keep the oldest matching pending session for promotion bookkeeping and drop all other matching `ui_id` entries during the same promotion pass
- New reconciliation hook/helper in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx):
  - `collectPendingSessionPromotions(pendingSessions: PendingSession[], serverChats: ChatSummary[]) -> Array<{ uiId: string, serverChatId: string }>`
  - Store `pendingSessionsRef.current = pendingSessions` in App so `applyStatePayload(...)` can compute promotions without a stale render closure.
  - Run inside `applyStatePayload(...)` in the same update turn, before the next render consumes derived chat collections.
  - Responsibilities:
    - scan unresolved pending sessions
    - join by exact `create_request_id` or already-known `server_chat_id`
    - return promotion operations for any newly materialized authoritative chat
  - `applyStatePayload(...)` must apply those promotions before calling `reconcilePendingSessions(...)`.
  - This helper is required so the design remains correct when state updates beat the create/start HTTP response back to the browser.
- `applyStatePayload(payload)` in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx)
  - Required order:
    - normalize payload
    - compute/apply server-driven promotions against the previous pending-session/UI state
    - set `hubState`
    - run `reconcilePendingSessions(...)` and `reconcilePendingChatStarts(...)`
  - Do not read `pendingSessions` from a stale render closure while computing promotions; use refs or functional setters only.
- `handleCreateChat(projectId, startSettings = null)` late-resolution rules are mandatory:
  - define `pendingSessionsRef.current` and use it in both success and error paths
  - a POST success may call `promotePendingChatIdentity(...)` only if `pendingSessionsRef.current` still contains `ui_id`
  - a POST error may remove optimistic state only if `pendingSessionsRef.current` still contains `ui_id`
  - if `pendingSessionsRef.current` no longer contains `ui_id`, treat both success and error as lifecycle no-ops and keep the authoritative chat visible
- `visibleChats` `useMemo` in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx)
  - This is the primary identity fix.
  - Stop rendering a matched authoritative chat under `id: session.ui_id` once the server chat is known.
  - Prefer rendering the authoritative chat object keyed by `chat.id`.
  - The optimistic placeholder row is only allowed while no authoritative chat match exists.
- `resolveServerChatId(chat)` and `hasServerChat(chat)` in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx)
  - Keep these helpers, but after promotion the common path should be the real `chat.id`.
- `findMatchingServerChatForPendingSession(session, serverChats, mappedServerIds)` in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js)
  - Match order:
    - exact `server_chat_id`
    - exact `create_request_id`
  - Remove the fallback scan that binds to an arbitrary `starting`/`running` chat from the same project.
- `reconcilePendingSessions(previousSessions, serverChatsById, nowMs)` in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js)
  - Do not attempt to infer UI-promotion completion inside this helper.
  - `promotePendingChatIdentity(...)` must remove the matched session immediately.
  - This helper remains responsible for stale-timeout cleanup and for dropping sessions whose authoritative chat disappeared after having already been seen on the server.
  - Retain stale-timeout cleanup for sessions that never materialize.
- `reconcilePendingChatStarts(previousPendingChatStarts, serverChatsById, nowMs)` in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js)
  - Preserve optimistic start only when the chat is missing on the server or still `starting`.
  - Remove the current behavior that keeps `stopped` chats visually `starting`.
- `reconcilePendingProjectChatCreates(previousPendingProjectChatCreates, pendingSessions, serverChats, nowMs)` in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js)
  - Clear the project-level pending-create spinner once the create request is joined to a specific authoritative chat, regardless of whether that chat is `starting`, `running`, `failed`, or `stopped`.
  - Do not rely on same-project startup heuristics.
- `queueStateRefresh()` in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx)
  - Use this helper for create/start lifecycle refreshes after the repair.
  - Do not add new raw `refreshState()` calls in the repaired create/start path.
- `reconcileProjectChatsFlexLayoutJson(existingLayoutJson, chats, projectId)` in [`web/src/flexLayoutState.js`](/home/joew/projects/agent_hub/web/src/flexLayoutState.js)
  - This is secondary cleanup, not the main identity repair.
  - Implementation must ensure project chat tabs converge on the authoritative `chat.id`.
  - If this helper participates in the fix, it must preserve selected-tab continuity when replacing a `pending-*` tab with the authoritative `chat.id`.
- New helper in [`web/src/flexLayoutState.js`](/home/joew/projects/agent_hub/web/src/flexLayoutState.js):
  - `rekeyProjectChatPaneTabIds(layoutJson, oldChatId, newChatId) -> layoutJson`
  - This helper is required for this feature; do not leave it as an implementation choice.
  - It must:
    - rewrite both tab `id` and `config.chat_id` for matching `project-chat-pane` tabs
    - preserve existing tab ordering and selected-tab indexes
    - dedupe if both old and new ids already exist, keeping the authoritative `newChatId` tab only once

### Backend Function Inventory

- `ProjectService.create_and_start_chat(self, project_id: str, *, agent_args: list[str] | None = None, agent_type: str | None = None, request_id: str | None = None) -> dict[str, Any]` in [`src/agent_hub/services/project_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/project_service.py)
  - Keep `_chat_create_lock`.
  - Resolve an existing chat by `(project_id, request_id)` before creation.
  - If the same `(project_id, request_id)` is reused with different `agent_type` or `agent_args`, the existing chat configuration wins; do not mutate the persisted chat or create a replacement chat.
  - The API response for a reused chat must reflect the existing persisted chat configuration; do not rewrite returned `agent_type` or `agent_args` from the retry request.
  - If multiple persisted chats already exist for the same `(project_id, request_id)`, do not create another chat:
    - deterministically prefer an existing `running` chat, else `starting`, else the earliest-created remaining chat
    - emit a warning log with all conflicting chat ids
  - Return the existing chat record for all previously created states after ensuring startup semantics are correct:
    - `starting` => return unchanged
    - `running` => return unchanged
    - `failed` or `stopped` => restart the same chat and return that same chat id
  - Add structured logs that distinguish:
    - `create_request_new_chat`
    - `create_request_reused_chat`
    - `create_request_restarted_existing_chat`
  - Each lifecycle log message must include, as plain key/value text in the message body:
    - `event`
    - `project_id`
    - `request_id`
    - `chat_id`
    - `chat_status`
    - `agent_type`
  - If a retry reuses an existing chat whose persisted config differs from the incoming request config, log the reused event with `config_mismatch=true` and still return/restart the original chat unchanged.
  - If restart of an existing failed/stopped chat raises, propagate the error unchanged, preserve the original `create_request_id -> chat.id` mapping, and do not create a second chat.
- `RuntimeService.start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]` in [`src/agent_hub/services/runtime_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/runtime_service.py)
  - Preserve the existing `starting` and `running` conflict guards.
  - Ensure failure paths do not leave ambiguous startup state:
    - if startup fails before spawn completion, the chat must be `failed`
    - if startup succeeds, the chat must be `running`
  - Keep the current lock discipline around state transitions.
- `AppStateService.state_payload(self) -> dict[str, Any]` in [`src/agent_hub/services/app_state_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/app_state_service.py)
  - Continue serializing `create_request_id`.
  - If implementation needs extra join metadata, prefer additive ephemeral fields over schema redesign.
- `HubState._chat_for_create_request(self, *, state: dict[str, Any], project_id: str, request_id: str) -> dict[str, Any] | None` in [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py)
  - Keep lookup semantics scoped to exact `(project_id, request_id)`.
  - Update this helper and its tests together with `ProjectService.create_and_start_chat(...)` so duplicate matches are resolved deterministically rather than by dictionary iteration order.
- `api_start_new_chat_for_project(project_id: str, request: Request) -> dict[str, Any]` in [`src/agent_hub/api/routes.py`](/home/joew/projects/agent_hub/src/agent_hub/api/routes.py)
  - Preserve the existing response shape unless implementation proves additional metadata is required.
  - Any route-layer payload or validation change must be covered by the existing route tests in [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py).

### Backend Lifecycle Semantics

- `ProjectService.create_and_start_chat(...)` must not create a new chat after a matching chat is found for `(project_id, request_id)`, even if `start_chat(...)` for that reused chat fails.
- `RuntimeService.start_chat(...)` failure semantics for this feature are:
  - before process spawn succeeds: persisted chat transitions to `failed` with `start_error` populated
  - after process spawn succeeds: persisted chat is either `running`, or if the chat was concurrently removed/closed, the existing close/remove semantics win unchanged
- `AppStateService.state_payload(...)` must not synthesize a same-project optimistic join hint; `create_request_id` remains the only required optimistic join key.

## Rendering Rules

- Chat-card/tab status derives from server truth once a server chat exists.
- Optimistic row copy is fixed:
  - title: `New Chat`
  - subtitle: `Creating workspace and starting worker...`
  - status: `starting`
- Failed authoritative rows must display the normal failed styling and `start_error`.
- The project-level `New chat` button spinner is scoped only to the active create request and must clear once the authoritative chat is attached or the request errors.
- Promotion from `pending-*` to `chat.id` must preserve row position and selected chat-tab continuity; the authoritative chat must not jump to the end of the list/layout as a side effect of convergence.

## Concurrency Model

- Backend:
  - `_chat_create_lock` serializes create/start for project chat creation requests.
  - `_runtime_lock` serializes runtime lifecycle transitions for a chat.
- Frontend:
  - `projectChatCreateLocksRef` remains the per-project local guard against accidental double submit in one browser session.
  - Browser state refreshes, websocket snapshots, and create/start HTTP responses may arrive in any order.
  - A server-driven promotion may happen while the originating POST promise is still pending; promotion logic therefore owns clearing the local project create lock.
  - The implementation must therefore be order-independent:
    - if `/api/state` publishes the chat before the POST returns, the optimistic row still joins correctly by `create_request_id`
    - if the POST returns before `/api/state` includes the chat, the optimistic row still converges correctly by `server_chat_id`
    - if `/api/state` publishes `failed` or `stopped` before a delayed POST success handler runs, that delayed success handler must not enqueue a fresh pending-start overlay

## Error Model

- `POST /api/projects/{project_id}/chats/start` keeps returning `200` with `{ "chat": ... }` for successful create-or-reuse.
- Invalid project/build-state errors remain unchanged.
- Duplicate start of the same already-starting chat remains `409 Chat is already starting.`
- A failed runtime launch must surface via the authoritative chat record with `status == failed` and populated `start_error`; the frontend must not continue to show a startup placeholder after that state arrives.

## Implementation Notes

- Keep the patch narrow. This is a lifecycle repair, not a UI redesign.
- Prefer adding small pure helpers in [`web/src/chatPendingState.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.js) and small state-migration helpers in [`web/src/App.jsx`](/home/joew/projects/agent_hub/web/src/App.jsx) over spreading conditional logic across render branches.
- If a project-flex-layout tab can still keep a stale `pending-*` `chat_id`, treat that as a bug in identity promotion and fix it in the same change.
- Use the explicit `rekeyProjectChatPaneTabIds(...)` helper in [`web/src/flexLayoutState.js`](/home/joew/projects/agent_hub/web/src/flexLayoutState.js); do not rely on generic flex-layout reconciliation to preserve the selected pending tab.
- Do not introduce a new persisted backend lifecycle table or token system for this fix. The intended repair is a single authoritative chat lifecycle plus an ephemeral placeholder view until the server chat exists.
- Preserve keyboard behavior and current button placement.
- Prefer functional React state updates in promotion helpers so HTTP-response and state-refresh arrivals cannot stomp each other with stale closures.

## Test Plan

### Frontend Unit Coverage

- Extend [`tests/test_web_pending_state.py`](/home/joew/projects/agent_hub/tests/test_web_pending_state.py):
  - request-id matching joins a pending session only to the matching chat
  - same-project fallback does not bind a pending session to unrelated running/starting chats
  - `reconcilePendingChatStarts(...)` drops pending-start when server status becomes `stopped`
  - `reconcilePendingChatStarts(...)` drops pending-start when server status becomes `failed`
  - replace the current assertion that `stopped` + pending-start should still render as `starting`
- Extend [`web/src/chatPendingState.test.js`](/home/joew/projects/agent_hub/web/src/chatPendingState.test.js):
  - project create pending clears when the matched authoritative chat exists
  - project create pending remains only while no authoritative chat has materialized
- Add frontend identity-promotion regression coverage in [`web/src/chatIdentityState.test.js`](/home/joew/projects/agent_hub/web/src/chatIdentityState.test.js):
  - one optimistic row becomes one authoritative row
  - duplicate promotion is a no-op
  - `openChats`, `openChatDetails`, `openChatLogs`, `pendingChatLogLoads`, `chatStaticLogs`, `showArtifactThumbnailsByChat`, `collapsedTerminalsByChat`, `fullscreenChatId`, and `artifactPreview.chatId` survive `pending-* -> chat.id` promotion
  - if both `ui_id` and `serverChatId` keys already exist in a keyed UI map, the authoritative `serverChatId` entry is retained and the `ui_id` entry is removed
  - project create spinner/lock clears on server-driven promotion before the POST promise settles
  - project flex-layout JSON rewrites `config.chat_id` and tab ids without changing the selected chat tab
  - `/api/state` arriving before POST success and POST success arriving before `/api/state` both converge to one authoritative row
  - late POST error after state-driven attachment does not delete the authoritative chat
  - late POST success after prior state-driven attachment is a no-op
  - late POST success after the server has already published `failed` or `stopped` does not add `pendingChatStarts[chat.id]`

### Backend Unit Coverage

- Extend [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py):
  - duplicate create requests with the same `request_id` never create a second chat id
  - same `request_id` in two different projects does not cross-match chats
  - same `request_id` with different `agent_type`/`agent_args` does not mutate the original chat
  - `create_and_start_chat(...)` restarts a failed existing chat instead of creating a new one
  - `create_and_start_chat(...)` restarts a stopped existing chat instead of creating a new one
  - restart failure for a failed/stopped reused chat preserves the original chat id and mapping
  - startup failure leaves the authoritative chat in `failed`, not `starting`
  - implementation detail for the startup-failure test:
    - patch `LaunchProfileService.prepare_chat_launch_context(...)` or `_spawn_chat_process(...)` to raise before a process is returned
    - assert the persisted chat reloads as `failed` with non-empty `start_error`
  - retain coverage for close/remove-during-launch cases:
    - `test_start_chat_does_not_overwrite_chat_closed_during_launch`
    - `test_start_chat_failure_does_not_overwrite_chat_closed_during_launch`
    - `test_start_chat_stops_process_when_chat_removed_before_completion`

### Integration Coverage

- Extend [`tests/integration/test_hub_chat_lifecycle_api.py`](/home/joew/projects/agent_hub/tests/integration/test_hub_chat_lifecycle_api.py):
  - repeated `POST /api/projects/{project_id}/chats/start` with the same `request_id` returns one chat id
  - direct start conflict for `starting` remains `409`
  - state snapshots include `create_request_id` for newly created chats
  - failure/retry path continues to reuse the same chat id
  - implementation detail for the failure/retry integration case:
    - patch the first start attempt to fail before process spawn completes
    - assert the first HTTP response is a failure and `/api/state` shows one `failed` chat with the requested `create_request_id`
    - retry the same `request_id`
    - assert the retry returns `200` and the same `chat.id`
  - the same `request_id` used in two different projects yields two different chat ids
  - duplicate persisted request-id state reuses one deterministic chat id and does not create a third chat

### UI Evidence Coverage

- Required during implementation because this is a user-visible rendering fix:
  - default state: project row before create
  - loading state: after `New chat` click while optimistic row exists
  - success state: authoritative running chat with no phantom duplicate
  - error state: authoritative failed chat with failed styling, not startup styling
  - responsive state: same lifecycle on narrow/mobile width if the changed surface renders there

## Verification Plan

No repo-local `./make.sh` wrapper is present in this checkout. Until one exists, implementation should run the direct commands below and update this section if the repository later standardizes a wrapper.

Implementation must not add or invent a new `./make.sh` wrapper as part of this feature just to satisfy verification.

- Command: `uv run python -m pytest tests/test_hub_and_cli.py -k "create_and_start_chat_reuses_existing_request_id_chat or create_and_start_chat_reuses_existing_starting_request_id_chat or create_and_start_chat_retries_existing_failed_request_id_chat or create_and_start_chat_retries_existing_stopped_request_id_chat or create_and_start_chat_serializes_duplicate_request_id_calls or create_and_start_chat_fails_fast_when_start_raises or state_payload_includes_create_request_id_for_chat_matching or start_chat_rejects_duplicate_start_when_chat_is_starting or start_chat_does_not_overwrite_chat_closed_during_launch or start_chat_failure_does_not_overwrite_chat_closed_during_launch or start_chat_stops_process_when_chat_removed_before_completion or project_chat_start_route_passes_request_id_when_present"`
  - Expected: all selected backend lifecycle tests pass.
- Command: `uv run python -m pytest tests/integration/test_hub_chat_lifecycle_api.py -k "project_chat_start_is_idempotent_with_request_id or direct_chat_start_returns_conflict_when_chat_is_already_starting or chat_lifecycle_routes_and_events_snapshot"`
  - Expected: all selected lifecycle API tests pass.
- Command: `uv run python -m pytest tests/test_web_pending_state.py`
  - Expected: pending-state regression tests pass.
- Command: `cd web && node --test src/chatPendingState.test.js src/chatIdentityState.test.js`
  - Expected: frontend pending create reconciliation and identity-promotion tests pass.

## PR Evidence Plan

Use the AGENTS.md required UI evidence flow during implementation:

1. `cd tools/demo && yarn install --frozen-lockfile`
2. Mirror auth/config into `UI_DATA_DIR=/workspace/tmp/agent-hub-ui-evidence`
3. Start the real app against the real backend on `http://127.0.0.1:8876`
4. Verify auth with `curl -fsS http://127.0.0.1:8876/api/settings/auth`
5. Capture Firefox screenshots for default/loading/success/error/responsive chat states
6. Keep screenshots untracked and attach public URLs in the PR
7. Stop evidence processes after capture

## Ambiguity Register

- Assumption: `create_request_id` is already present in all `/api/state` chat payloads and remains the correct frontend join key. Existing tests suggest this is true.
- Assumption: a same-project heuristic is not required for chat creation anymore once `create_request_id` is consistently surfaced.
- Assumption: preserving the existing HTTP response schema is preferable to adding a second create-token field unless implementation proves a gap.
- Assumption: non-authoritative UI caches/refs may be invalidated and rebuilt after promotion rather than rekeyed in place, provided they do not reintroduce a stale `pending-*` identity.
- Open question for repo maintenance: whether a canonical `./make.sh` wrapper will be added later. If so, replace the direct verification commands above with the approved wrapper commands.
