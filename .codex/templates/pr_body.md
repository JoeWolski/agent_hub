## Summary
- What changed and why.

## Changes
- Key implementation details by subsystem.
- Codex multi-agent workflow used for this PR:
  - Launch orchestrator: `codex -C <repo-root>`
  - Workflow trigger: `implement <feature name>`
  - Run directory: `docs/<appropriate-subsystem>/<feature-name>/`
  - Model routing:
    - main-thread orchestration/spec ownership: `gpt-5.4`
    - implementation workers: `gpt-5.3-codex-spark`
    - adversarial review workers: `gpt-5.3-codex-spark`
  - Orchestrator runs:
    - `tools/codex/collect_evidence.sh --manifest docs/<appropriate-subsystem>/<feature-name>/validation/manifest.txt --output docs/<appropriate-subsystem>/<feature-name>/validation/validation_report.md`
    - `tools/codex/run_gate.sh --gate intake --run-dir docs/<appropriate-subsystem>/<feature-name>`
    - `tools/codex/run_gate.sh --gate design_review --run-dir docs/<appropriate-subsystem>/<feature-name>`
    - `tools/codex/run_gate.sh --gate implementation --run-dir docs/<appropriate-subsystem>/<feature-name>`
    - `tools/codex/run_gate.sh --gate verification --run-dir docs/<appropriate-subsystem>/<feature-name>`
    - `tools/codex/run_gate.sh --gate fresh_audit --run-dir docs/<appropriate-subsystem>/<feature-name>`
    - `tools/codex/run_gate.sh --gate pr_ready --run-dir docs/<appropriate-subsystem>/<feature-name>`
    (no manual gate/evidence commands required from user)
  - Fresh audit:
    - run by a newly spawned agent with no prior implementation context
    - emits `fresh_audit_report.md` with `Overall: PASS/FAIL`
  - Parallelization policy:
    - divide implementation into owned slices and do the largest/highest-risk changes first
    - reserve cleanup/small refactors for the end
    - divide review across implementation coverage, bug risk, and architecture/test quality
    - do not conclude while reviewer agents still report missing implementation or bugs
  - Delegate roles via `.codex/agents/*.md` and wait for all agents before
    integration
- Feedback revision cycles:
  - Feedback captured in `feedback_log.md`
  - Updated artifacts/code/tests revalidated automatically
  - PR stack refreshed and returned for review
- PR evidence discipline:
  - Visual evidence format: `.png` only when visuals are used
  - Planned visualizations from feature docs are implemented as specified
  - Each visualization has self-review assertion recorded:
    - clear/readable
    - legend-correct
    - no rendering artifacts/glitches
    - required visualization content present
  - PR body updated after each meaningful implementation/validation/evidence change

## Validation
- `command` : PASS/FAIL
- Include required command:
  - `build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733` : PASS/FAIL
- PR evidence checks:
  - planned `.png` visualization artifacts present: PASS/FAIL
  - visualization self-review completed: PASS/FAIL
  - PR body reflects latest evidence and validation state: PASS/FAIL

## Risks
- Assumptions
- Failure modes
- Residual risks and mitigations
