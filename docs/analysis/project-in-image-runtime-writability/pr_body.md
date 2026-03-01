## Summary
Re-land project-in-image snapshot writability with a deterministic bootstrap sequence and fix the reverted build failure where snapshot prepare attempted `docker exec` after the setup container had already exited.

## Changes
- `src/agent_cli/cli.py`
  - Removed the `--project-in-image` + `--prepare-snapshot-only` conflict.
  - Refactored snapshot bootstrap script to:
    - run setup script as runtime UID/GID via `setpriv` when copying project into image,
    - run ownership repair and writable probe inside bootstrap before container exit,
    - avoid post-exit `docker exec` ownership repair entirely.
  - Added `/workspace/tmp` daemon mount-source rewrite via `AGENT_HUB_TMP_HOST_PATH` for Docker volume/file mount sources in nested-daemon environments.
  - For copied-in-image snapshot setup runs, force setup container user to `0:0` so bootstrap can chown deterministically.
- `src/agent_hub/server.py`
  - Snapshot prepare command now passes `project_in_image=True` in both project snapshot launch paths.
  - Bumped snapshot schema version to `8` to invalidate pre-fix and reverted-v7 window snapshots.
- `tests/test_hub_and_cli.py`
  - Added/updated regression tests to enforce:
    - prepare snapshot command includes `--project-in-image`,
    - prepare-only + project-in-image is allowed and avoids project bind-mount,
    - repair/probe are embedded in bootstrap script before commit,
    - no `docker exec` repair command is emitted after setup.
- Codex multi-agent workflow used for this PR:
  - Launch orchestrator: `codex -C <repo-root>`
  - Workflow trigger: `implement project-in-image-runtime-writability`
  - Run directory: `docs/analysis/project-in-image-runtime-writability/`
  - Model routing:
    - coding/orchestration/review roles: `gpt-5.3-codex`
    - fast read-heavy triage roles only: `gpt-5.3-codex-spark`
  - Orchestrator maintains:
    - `docs/analysis/project-in-image-runtime-writability/validation/manifest.txt`
    - `docs/analysis/project-in-image-runtime-writability/validation/validation_report.md`
    - `docs/analysis/project-in-image-runtime-writability/gates.md` (`intake`, `design_review`, `implementation`, `verification`, `fresh_audit`, `pr_ready`)
    (no manual gate/evidence commands required from user)
  - Fresh audit:
    - run by a newly spawned agent with no prior implementation context
    - emits `fresh_audit_report.md` with `Overall: PASS/FAIL`
  - Delegate roles via `.codex/agents/*.md` and wait for all agents before integration
- Feedback revision cycles:
  - Feedback captured in `feedback_log.md`
  - Updated artifacts/code/tests revalidated automatically
  - PR stack refreshed and returned for review
- PR evidence discipline:
  - Visual evidence format: `.png` only
  - Planned visualizations from feature docs are implemented as specified
  - Each visualization has self-review assertion recorded:
    - clear/readable
    - legend-correct
    - no rendering artifacts/glitches
    - required visualization content present
  - PR body updated after each meaningful implementation/validation/evidence change

## Validation
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable/.venv uv run pytest tests/test_hub_and_cli.py -k "ensure_project_setup_snapshot_builds_once or snapshot_commit_resets_entrypoint_and_cmd or snapshot_prepare_only_allows_project_in_image_without_bind_mount or snapshot_runtime_project_in_image_repairs_project_ownership_before_commit" -q` : PASS
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable/.venv uv run pytest tests/test_hub_and_cli.py -k "project_in_image or ensure_project_setup_snapshot_builds_once or snapshot_commit_resets_entrypoint_and_cmd or snapshot_prepare_only_allows_project_in_image_without_bind_mount or snapshot_runtime_project_in_image_repairs_project_ownership_before_commit" -q` : PASS
- `curl -fsS -X PATCH http://host.docker.internal:8765/api/projects/28edad7d018f47a0989f00f93b9896d4 ... && curl -fsS http://host.docker.internal:8765/api/projects/28edad7d018f47a0989f00f93b9896d4/build-logs` : PASS (cached snapshot reuse path)
- `UV_PROJECT_ENVIRONMENT=/workspace/agent_hub_writable/.venv OPENAI_API_KEY=dummy uv run --project /workspace/agent_hub_writable agent_cli --agent-command codex --project /workspace/tmp/uncached-test/project --container-project-name agent_hub --agent-home-path /workspace/tmp/uncached-test/agent-home --config-file=/workspace/tmp/uncached-test/agent.config.toml --system-prompt-file=/workspace/tmp/uncached-test/SYSTEM_PROMPT.md --no-alt-screen --snapshot-image-tag agent-hub-setup-uncached-1772394861 --base-docker-context /workspace/tmp/uncached-test/project --base-dockerfile /workspace/tmp/uncached-test/project/docker/development/Dockerfile --prepare-snapshot-only --project-in-image --rw-mount /workspace/tmp:/workspace/tmp` : PASS
- PR evidence checks:
  - planned `.png` visualization artifacts present: PASS (not applicable; backend/runtime-only change)
  - visualization self-review completed: PASS (not applicable)
  - PR body reflects latest evidence and validation state: PASS

## Risks
- Assumptions
  - Runtime image includes `setpriv` (Ubuntu base image in this repo does).
- Failure modes
  - If a non-standard base image omits `setpriv`, setup-script user demotion would fail.
- Residual risks and mitigations
  - Nested-daemon path mapping still depends on `AGENT_HUB_TMP_HOST_PATH` being present and correct; validation includes successful uncached execution under that contract.
