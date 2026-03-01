# Design Spec: Project-In-Image Runtime Writability

## Design Goals
- Deterministically align snapshot ownership with runtime UID/GID used by chats.
- Remove mode coupling that allows snapshot builds to skip required ownership repair.
- Fail fast when image workspace is not writable by intended runtime user.

## Non-Goals
- Changing default runtime UID/GID selection strategy.
- Introducing permissive chmod-based workarounds.
- Refactoring unrelated snapshot/network/auth logic.

## Interfaces
- `HubState._prepare_agent_cli_command(...)`
  - Ensure snapshot-build invocation for project setup passes explicit intent for in-image workspace handling when snapshot is meant for project-in-image chats.
- `agent_cli.main(...)`
  - Ownership repair trigger should be keyed off snapshot workspace-copy mode (or equivalent deterministic condition), not only current launch mode.
- Optional helper interfaces:
  - Add a small `snapshot_workspace_mode` enum/string or boolean that explicitly captures whether setup copied project into image workspace.

Compatibility assumptions:
- Existing CLI args remain backward compatible.
- If new flag/semantic is introduced, default behavior for non-snapshot and bind-mounted flows remains unchanged.

## Data Flow
1. Hub starts project snapshot build (`prepare_snapshot_only`) for a project.
2. Hub passes explicit in-image workspace intent to agent_cli.
3. agent_cli setup container copies repo into image workspace.
4. agent_cli runs setup script.
5. agent_cli repairs ownership for container project path to runtime UID/GID.
6. agent_cli verifies writability probe as runtime user.
7. agent_cli commits snapshot image.
8. New chats launch with `--project-in-image` and reuse verified snapshot.

## Build/Test Impact
Impacted modules:
- `src/agent_hub/server.py` (snapshot command composition)
- `src/agent_cli/cli.py` (repair trigger and probe)
- `tests/test_hub_and_cli.py` (command/unit regression coverage)
- possibly `tests/integration/test_snapshot_builds.py` or equivalent integration coverage for writability.

Required tests:
- Unit: hub snapshot build command includes in-image ownership-repair-enabling mode.
- Unit: cli runs repair path in snapshot prepare flow for in-image workspace snapshots.
- Unit/Integration: failure path when ownership probe fails prevents commit.
- Integration: new chat launched from snapshot can write to project path as runtime user.

## Rollback Plan
- Revert ownership-trigger refactor and hub command wiring in a single commit.
- Increment snapshot schema version if needed to invalidate partially migrated snapshots.
- Restore prior behavior while retaining new tests as guardrails (updated to expected old behavior) only if rollback is unavoidable.
