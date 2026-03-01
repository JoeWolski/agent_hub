## Summary
- What changed and why.

## Changes
- Key implementation details by subsystem.
- Codex multi-agent workflow used for this PR:
  - Launch orchestrator: `codex -C <repo-root>`
  - Workflow trigger: `implement <feature name>`
  - Run directory: `docs/analysis/<feature-name>/`
  - Model routing:
    - coding/orchestration/review roles: `gpt-5.3-codex`
    - fast read-heavy triage roles only: `gpt-5.3-codex-spark`
  - Orchestrator maintains:
    - `docs/analysis/<feature-name>/validation/manifest.txt`
    - `docs/analysis/<feature-name>/validation/validation_report.md`
    - `docs/analysis/<feature-name>/gates.md` (`intake`, `design_review`, `implementation`, `verification`, `fresh_audit`, `pr_ready`)
    (no manual gate/evidence commands required from user)
  - Fresh audit:
    - run by a newly spawned agent with no prior implementation context
    - emits `fresh_audit_report.md` with `Overall: PASS/FAIL`
  - Delegate roles via `.codex/agents/*.md` and wait for all agents before
    integration
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
- `command` : PASS/FAIL
- Include required changed-scope commands:
  - `uv run pytest tests/<targeted_test>.py` : PASS/FAIL
  - `uv run pytest tests/test_hub_and_cli.py -k <targeted_case>` : PASS/FAIL
  - `cd web && yarn build` : PASS/FAIL (frontend changes only)
- PR evidence checks:
  - planned `.png` visualization artifacts present: PASS/FAIL
  - visualization self-review completed: PASS/FAIL
  - PR body reflects latest evidence and validation state: PASS/FAIL

## Risks
- Assumptions
- Failure modes
- Residual risks and mitigations
