# Codex Multi-Agent Workflows

This repo supports two multi-agent workflows:

1. Project design documentation
2. Project implementation

All feature artifacts live under `docs/analysis/<feature-name>/`.

## Workflow 1: Project Design Documentation

Goal: produce implementation-ready design docs and iterate on feedback.

User flow:

1. Start a Codex CLI chat at repo root.
2. Describe the desired feature and request design docs.
3. Agents create and update design docs.
4. Provide feedback; agents update docs.
5. Iterate until satisfied.

Agent behavior requirements:

- Create/use `docs/analysis/<feature-name>/`.
- Save docs in that run directory:
  - `feature_plan.md`
  - `verification.md`
  - `design_spec.md`
  - `.codex/tasks/analysis/<feature-name>/task-*.md`
  - `feedback_log.md`
- Use multi-agent delegation when it improves speed/quality.
- Do not modify product source code during documentation workflow.
- Add an explicit PR evidence planning step for every feature:
  - define required evidence artifacts
  - if visual evidence is needed, use `.png` only
  - predefine exact visualization artifacts and at-a-glance correctness argument for each
  - include required self-review criteria before PR-body inclusion

## Workflow 2: Project Implementation

Goal: implement `implement <feature name>` and return a ready-to-review PR
stack.

User flow:

1. Start a Codex CLI chat at repo root.
2. Say: `implement <feature name>`.
3. Agents implement and provide PR stack.
4. Provide PR feedback; agents update docs/code/validation/PR stack.
5. Iterate until satisfied.

Agent behavior requirements:

- Resolve run directory from feature name:
  - `docs/analysis/<feature-name>/`
- Load design docs from workflow 1.
- Implement code/tests and validation.
- Run evidence and gates autonomously by maintaining run artifacts:
  - `<run-dir>/validation/manifest.txt`
  - `<run-dir>/validation/validation_report.md`
  - `<run-dir>/gates.md` with statuses for `intake`, `design_review`, `implementation`, `verification`, `fresh_audit`, `pr_ready`
- Require fresh-context audit before PR-ready:
  - spawn a brand-new fresh auditor agent
  - provide only design docs, task contracts, changed-file diffs, and validation evidence
  - write `<run-dir>/fresh_audit_report.md` with `Overall: PASS` to unblock `pr_ready`
- Require incremental testing during implementation:
  - run baseline + chunk-level + integration checks throughout development
  - do not wait until end-of-feature to run first meaningful tests
  - keep execution logs updated as failures are discovered/fixed
  - for longer-running flows, run a short smoke check before full runs to verify wiring/output paths first
- Require rich diagnostics during implementation testing:
  - Python/JS: use appropriate verbose logging with useful context while diagnosing failures
  - run tests with maximum practical log verbosity while diagnosing failures
- Update PR stack without requiring user-run commands.
- Keep PR body continuously up to date as implementation/evidence evolves.
- On feedback, run full revision cycle automatically and return updated PR
  stack.
- Require visualization self-review before PR-body inclusion:
  - clear/readable
  - legend matches plotted data and labels
  - no rendering artifacts/bugs/glitches
  - required visualization content present

## Scaffolding

Agents initialize feature directories directly in-chat using `.codex/templates/`.
No user-run setup script is required.

## Model Profiles

Default model/reasoning policy is defined in `.codex/config.toml`:
- default coding and orchestration: `gpt-5.3-codex` with `medium` reasoning effort
- deep review: `gpt-5.3-codex` with `high` reasoning effort
- fast read-heavy triage: `gpt-5.3-codex-spark` with `low` reasoning effort

Use Spark profiles only for non-critical read-heavy subtasks, not primary code editing.

## Gate/Evidence Notes

This repository does not require `tools/codex/*` gate scripts. Agents should keep gate/evidence state in the run directory artifacts listed above.
