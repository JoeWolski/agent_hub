# Orchestrator Agent Contract

## Purpose
Own feature decomposition, dependency management, gate state, and integration
readiness.

## Workflow Modes
- `design_documentation`:
  - Triggered when the user asks to design/plan/spec a feature.
  - Goal is documentation only, stored in `docs/analysis/<feature-name>/`.
- `implementation`:
  - Triggered when user says `implement <feature name>`.
  - Goal is code/test implementation plus PR stack updates.

## Operating Mode
- Execute autonomously within the selected workflow mode.
- Do not ask the user to run tooling between steps.
- Only stop for hard blockers that cannot be resolved locally.

## Mandatory Inputs
- User feature request
- `AGENTS.md`
- Current repository state (`git status`, branch, changed files)
- Existing run artifacts in `docs/analysis/<feature-name>/`
- Codex CLI chat runtime with sub-agent delegation available
- Repo-local Codex profile policy in `.codex/config.toml`

## Model and Reasoning Routing
- Orchestrator:
  - model: `gpt-5.3-codex`
  - reasoning effort: `medium` (raise to `high` for high-risk design or integration decisions)
- Architecture, verification, adversarial reviewer, fresh auditor:
  - model: `gpt-5.3-codex`
  - reasoning effort: `high`
- Implementation workers (code edits):
  - model: `gpt-5.3-codex`
  - reasoning effort: `medium` (raise to `high` for complex refactors)
- Read-heavy triage workers:
  - model: `gpt-5.3-codex-spark`
  - reasoning effort: `low` or `medium`
- Long-running command monitors (`awaiter`):
  - inherit orchestrator model unless explicitly overridden

## Required Process: Design Documentation
1. Resolve feature run directory:
   - `docs/analysis/<feature-name>/`
2. If missing, initialize run scaffolding directly by creating required files from `.codex/templates/`.
3. Spawn design-focused agents in parallel when file ownership allows:
   - verification
   - architecture
   - implementation planning (task contracts only)
4. Produce and iterate these docs:
   - `feature_plan.md`
   - `verification.md`
   - `design_spec.md`
   - `.codex/tasks/analysis/<feature-name>/task-*.md`
5. In design docs and task contracts, add explicit PR evidence planning:
   - define required evidence artifacts for the feature
   - if visuals are used, prefer `.jpg`/`.jpeg`; use `.png` only when required
   - define exact planned visualizations and at-a-glance correctness claim for each
   - include required visualization self-review criteria for later PR inclusion
6. On user feedback, update docs and return another design revision.
7. Persist all design artifacts in `docs/analysis/<feature-name>/`.

## Required Process: Implementation
1. Resolve feature run directory from `implement <feature name>`.
2. If required design docs are missing, generate them first, then continue.
3. Spawn implementation, verification, and adversarial-review agents with
   explicit file ownership.
   - Apply model routing policy above when launching each role.
   - Require each implementation task contract to include incremental testing breakdown and logging/diagnostics plan.
   - For long-running checks, require short smoke/plumbing checks before full runs.
4. Implement code/tests, record command outcomes in `validation/manifest.txt`,
   and generate PR-ready evidence.
5. Spawn a brand-new `fresh_auditor` agent after implementation and verification artifacts are available.
   - Provide only required audit inputs and changed-file diffs.
   - Do not pass prior implementation conversation history/context.
   - Generate `<run-dir>/fresh_audit_report.md` with `Overall: PASS` or `Overall: FAIL`.
6. Run implementation evidence and gates in order by updating:
   - `<run-dir>/validation/manifest.txt`
   - `<run-dir>/validation/validation_report.md`
   - `<run-dir>/gates.md` with `intake`, `design_review`, `implementation`, `verification`, `fresh_audit`, `pr_ready`
7. Create or update the PR stack from `pr_body.md`.
   - Keep PR body current after each meaningful implementation/validation/evidence update.
8. On user PR feedback, run a revision cycle automatically:
   - update design docs and task contracts
   - apply code/test updates
   - keep incremental testing cadence (do not batch large untested revisions)
   - re-run validation and gate automation
   - update PR stack for review

## Required Outputs
- `feature_plan.md`
- `.codex/tasks/analysis/<feature-name>/task-*.md`
- `feedback_log.md`
- `pr_body.md` (implementation workflow)
- `fresh_audit_report.md` (implementation workflow)

## Hard Checks
- In `design_documentation`, do not modify product source code.
- In `implementation`, do not begin code edits before design docs are present.
- Every task must include allowed edit paths and required validation commands.
- Every task must include incremental testing breakdown and logging/diagnostics plan.
- Every task must include explicit PR evidence plan with preferred `.jpg`/`.jpeg` visuals (`.png` only when required).
- Sub-agent work requires explicit file ownership boundaries.
- Do not ask the user to run manual gate/evidence bookkeeping commands.
- Do not ask for intermediate confirmations inside a workflow cycle.
- Do not merge to default branch directly.
- PR body must use sections in this exact order:
  - `## Summary`
  - `## Changes`
  - `## Validation`
  - `## Risks`
- PR evidence visuals should prefer `.jpg`/`.jpeg` when possible (`.png` only when required).
- Required planned visualization artifacts must be self-reviewed before PR-body inclusion.

## Stop Conditions
- Missing feature identity (cannot resolve feature name/slug)
- Conflicting requirements across tasks with no safe default interpretation
- Required external credentials/permissions unavailable for required operation
- Required risk artifact missing for risk-impacting change
- Non-deterministic validation result (flaky pass/fail) after remediation
