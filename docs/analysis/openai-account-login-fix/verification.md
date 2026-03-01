# Verification Plan: Runtime UID/GID Propagation

## Scope
Hub-to-agent_cli identity propagation for snapshot/chat launch command construction.

## Assumptions
- Hub `local_uid/local_gid` represent intended runtime identity.
- `agent_cli` respects explicit `--local-uid/--local-gid` when provided.

## Hazards
- Snapshot project ownership diverges from runtime user.
- Chat runtime runs with implicit process identity rather than explicit intended identity.
- Regression to prior mount/snapshot behavior.

## Failure Modes
- Missing uid/gid args in hub-generated `agent_cli` command.
- Supplementary groups omitted unexpectedly.
- Tests only checking partial command structure miss identity regressions.

## Required Controls
- Always emit `--local-uid` and `--local-gid` in hub launch commands.
- Emit `--local-supplementary-gids` when available.
- Validate both snapshot and chat launch command paths in tests.

## Verification Mapping
- `test_ensure_project_setup_snapshot_builds_once` asserts uid/gid args.
- `test_start_chat_uses_claude_agent_command_when_selected` asserts uid/gid args.
- Focused `pytest` suites cover snapshot/chat command composition and project-in-image snapshot wiring.

## Residual Risk
- If hub starts under a different OS user than expected, explicit propagation will still reflect hub runtime identity.
