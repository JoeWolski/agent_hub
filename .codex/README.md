# Codex Multi-Agent Workflows

This repo supports two multi-agent workflows:

1. Project design documentation
2. Project implementation

All feature artifacts live under `docs/<appropriate-subsystem>/<feature-name>/`.

## Workflow 1: Project Design Documentation

Goal: produce implementation-ready design docs and iterate on feedback.

User flow:

1. Start a Codex CLI chat at repo root.
2. Describe the desired feature and request design docs.
3. Agents create and update design docs.
4. Provide feedback; agents update docs.
5. Iterate until satisfied.

Agent behavior requirements:

- Create/use `docs/<appropriate-subsystem>/<feature-name>/`.
- Save docs in that run directory:
  - `feature_plan.md`
  - `verification.md`
  - `design_spec.md`
  - `.codex/tasks/<appropriate-subsystem>/<feature-name>/task-*.md`
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
  - `docs/<appropriate-subsystem>/<feature-name>/`
- Load design docs from workflow 1.
- Implement code/tests and validation.
- Run evidence and gates autonomously:
  - `tools/codex/collect_evidence.sh --manifest <run-dir>/validation/manifest.txt --output <run-dir>/validation/validation_report.md`
  - `tools/codex/run_gate.sh --gate intake --run-dir <run-dir>`
  - `tools/codex/run_gate.sh --gate design_review --run-dir <run-dir>`
  - `tools/codex/run_gate.sh --gate implementation --run-dir <run-dir>`
  - `tools/codex/run_gate.sh --gate verification --run-dir <run-dir>`
  - `tools/codex/run_gate.sh --gate fresh_audit --run-dir <run-dir>`
  - `tools/codex/run_gate.sh --gate pr_ready --run-dir <run-dir>`
- Require fresh-context audit before PR-ready:
  - spawn a brand-new fresh auditor agent
  - provide only design docs, task contracts, changed-file diffs, and validation evidence
  - write `<run-dir>/fresh_audit_report.md` with `Overall: PASS` to unblock `pr_ready`
- Require incremental testing during implementation:
  - run baseline + chunk-level + integration checks throughout development
  - do not wait until end-of-feature to run first meaningful tests
  - keep execution logs updated as failures are discovered/fixed
  - for simulation/offline-log pipelines, run a short plumbing check before full runs:
    - sim/log time cap: 5 seconds
    - wall-clock cap: 30 seconds
    - verify wiring/schema/output channel/manifest correctness first
- Require rich diagnostics during implementation testing:
  - C++: use `LERROR`, `LWARN`, `LINFO`, `LDEBUG`, and liberal `LDEBUG_VERBOSE` with useful verbosity levels
  - Python: use equivalent `logging` levels with detailed debug traces
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
- main-thread orchestration/spec ownership: `gpt-5.4` with `high` reasoning effort
- implementation workers: `gpt-5.3-codex-spark` with `medium` reasoning effort
- adversarial spec/implementation review: `gpt-5.3-codex-spark` with `medium` reasoning effort
- read-heavy exploration/naive implementation checks: `gpt-5.3-codex-spark` with `medium` reasoning effort

Implementation and review both use divide-and-conquer fan-out:
- split implementation into multiple owned slices and start with the largest/highest-risk changes first
- split review across implementability, bug/risk, and architecture/test-quality lenses
- do not stop an implementation turn until reviewer agents explicitly report the ExecPlan fully implemented, implemented well, and bug free

## Gate/Evidence Scripts

These are internal workflow tools for agents (not user-run requirements):

- `tools/codex/run_gate.sh`
- `tools/codex/collect_evidence.sh`
- `tools/codex/upload_artifacts.sh`
