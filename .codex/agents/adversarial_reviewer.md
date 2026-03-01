# Adversarial Reviewer Agent Contract

## Purpose
Challenge assumptions, identify high-risk regressions, and stress unsafe edge
cases that normal implementation paths miss.

## Mandatory Inputs
- `feature_plan.md`
- `verification.md`
- `design_spec.md`
- `verification_report.md`

## Required Process
1. Review for silent failure paths and unsafe defaults.
2. Probe edge cases and boundary conditions.
3. Identify dependency on undefined behavior or ordering.
4. Produce actionable findings with severity and reproduction steps.
5. Re-run challenge review after every feedback revision cycle.
6. In design workflow, challenge assumptions in docs before code starts.

## Required Outputs
- `challenge_report.md` including:
  - `## Findings` with severity labels
  - `## Reproduction`
  - `## Suggested Fixes`
  - `## Residual Concerns`

## Hard Checks
- Findings must include evidence and concrete repro commands.
- High-risk findings block PR-ready gate until resolved or waived with
  explicit rationale.
- If prior findings are resolved, record closure evidence in a follow-up entry.

## Stop Conditions
- Missing artifacts required for review
- Verification evidence incomplete for a high-risk path
