# Validation Report: Runtime UID/GID Propagation

## Scope
- Hub command generation for snapshot setup and chat start.
- Runtime identity propagation (`--local-uid`, `--local-gid`, supplementary gids).

## Results
- Focused identity regression checks passed for snapshot and chat command paths.
- Broader targeted command-composition checks passed for claude/gemini launch and snapshot flow.
- Project-in-image snapshot command-path checks passed.

## Commands
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "test_start_chat_uses_claude_agent_command_when_selected or test_ensure_project_setup_snapshot_builds_once"` -> PASS (`2 passed, 319 deselected`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "start_chat_uses_claude_agent_command_when_selected or start_chat_uses_gemini_agent_command_when_selected or ensure_project_setup_snapshot_builds_once or ensure_project_setup_snapshot_passes_git_identity_env_for_pat"` -> PASS (`4 passed, 317 deselected`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "project_in_image and snapshot"` -> PASS (`3 passed, 318 deselected`)

## Notes
- No UI rendering changes were introduced.
- No mount-path or snapshot strategy behavior was changed; only identity argument propagation at hub command construction.
