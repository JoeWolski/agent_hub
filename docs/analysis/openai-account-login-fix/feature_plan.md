# Feature Plan: Runtime UID/GID Propagation for Chat Launches

## Objective
Ensure chat runtime and snapshot setup always run with the hub runtime user's UID/GID so project ownership inside snapshot-backed chats matches the effective runtime user.

## Scope
- Agent CLI command assembly in hub chat/snapshot launch paths.
- Explicit propagation of local UID/GID (and supplementary gids when present).
- Targeted regression tests for chat launch and snapshot command composition.

## Non-Scope
- Changing OpenAI login callback forwarding behavior.
- Changing container mount topology, snapshot copy strategy, or bridge-network fallback logic.

## Evidence Plan
- Verify snapshot launch command includes `--local-uid` and `--local-gid`.
- Verify chat start command includes `--local-uid` and `--local-gid`.
- Run focused `pytest` suites for changed command-building paths.
