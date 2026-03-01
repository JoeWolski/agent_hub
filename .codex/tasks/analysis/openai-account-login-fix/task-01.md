# Task 01: Propagate Runtime UID/GID into Chat and Snapshot Launch Commands

## Status
REVISED_COMPLETE

## Scope
- Ensure all hub-generated `agent_cli` launch commands include explicit local runtime UID/GID.
- Keep supplementary gids propagation explicit when present.
- Add regression assertions in snapshot and chat command tests.

## Allowed Edit Paths
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/openai-account-login-fix/**`

## Incremental Validation Log
1. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "test_start_chat_uses_claude_agent_command_when_selected or test_ensure_project_setup_snapshot_builds_once"` -> PASS (`2 passed, 319 deselected`)
2. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "start_chat_uses_claude_agent_command_when_selected or start_chat_uses_gemini_agent_command_when_selected or ensure_project_setup_snapshot_builds_once or ensure_project_setup_snapshot_passes_git_identity_env_for_pat"` -> PASS (`4 passed, 317 deselected`)
3. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "project_in_image and snapshot"` -> PASS (`3 passed, 318 deselected`)

## Remaining Risks
- Runtime identity remains anchored to hub runtime process identity (`os.getuid/os.getgid`) unless future configuration adds explicit overrides.
