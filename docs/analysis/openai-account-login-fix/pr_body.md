## Summary
Propagates explicit runtime identity (`uid/gid`) from hub into all hub-generated `agent_cli` launch commands so snapshot-backed chat project ownership and runtime user identity stay aligned.

## Changes
- Updated `HubState._prepare_agent_cli_command` to always append:
  - `--local-uid <hub local uid>`
  - `--local-gid <hub local gid>`
- Added conditional propagation of `--local-supplementary-gids` when the hub has supplemental groups.
- Added/updated targeted tests to assert uid/gid propagation in:
  - snapshot command generation (`test_ensure_project_setup_snapshot_builds_once`)
  - chat launch command generation (`test_start_chat_uses_claude_agent_command_when_selected`)
- Updated run artifacts and verification docs under `docs/analysis/openai-account-login-fix/`.

## Validation
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "test_start_chat_uses_claude_agent_command_when_selected or test_ensure_project_setup_snapshot_builds_once"` -> PASS (`2 passed, 319 deselected`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "start_chat_uses_claude_agent_command_when_selected or start_chat_uses_gemini_agent_command_when_selected or ensure_project_setup_snapshot_builds_once or ensure_project_setup_snapshot_passes_git_identity_env_for_pat"` -> PASS (`4 passed, 317 deselected`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "project_in_image and snapshot"` -> PASS (`3 passed, 318 deselected`)

## Risks
- Runtime identity source is still hub process identity (`os.getuid/os.getgid`); environments expecting a different identity source may need explicit configuration support in future.
- Supplementary gids are only passed when detected on hub startup; dynamic group membership changes after startup are out of scope.
