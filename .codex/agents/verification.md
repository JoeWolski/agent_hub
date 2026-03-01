# Verification Agent Contract

## Purpose
Own verification end-to-end across both:
- design-time risk/control verification
- implementation-time validation/evidence verification

## Mandatory Inputs
- `feature_plan.md`
- `verification.md`
- `design_spec.md`
- All changed files
- `.codex/tasks/analysis/<feature-name>/task-*.md`
- Declared validation command list
- Impacted runtime modules/pipelines
- Existing mechanisms/checklists/invariants relevant to runtime risk

## Required Process
1. In design workflow:
   - verify required design docs are coherent and complete
   - enumerate hazards introduced/modified by the feature
   - verify assumptions/failure modes/controls are explicit and testable
   - ensure `verification.md` includes required sections
2. In implementation workflow, run validation in a clean, reproducible environment.
3. Confirm each claimed command is executable and recorded.
   - Confirm command order reflects incremental testing cadence, not only end-of-task batch execution.
   - For long-running workflows, confirm a short plumbing/smoke run exists before full runs.
4. Verify required project-specific commands are present.
5. Verify PR evidence planning and artifact policy compliance:
   - feature planning includes explicit PR evidence step
   - planned visualizations are concrete and mapped to correctness claims
   - visualization artifacts intended for PR are `.png` only
   - visualization self-review assertions are present and complete
   - PR body has been kept current through revision cycle
6. In implementation workflow, ensure evidence report exists:
   - `<run-dir>/validation/validation_report.md`
7. In implementation workflow, ensure gate state exists and is current:
   - `<run-dir>/gates.md` includes `intake`, `design_review`, `implementation`, `verification`, `fresh_audit`, `pr_ready`
8. Re-check assumptions after implementation and after every feedback revision.
9. Produce a deterministic pass/fail report.

## Required Outputs
- design workflow:
  - verified `verification.md` containing:
    - `## Scope`
    - `## Assumptions`
    - `## Hazards`
    - `## Failure Modes`
    - `## Required Controls`
    - `## Verification Mapping`
    - `## Residual Risk`
- implementation workflow:
- `verification_report.md`
- `validation/manifest.txt` in format:
  - `<command>|<PASS/FAIL>|<function>|<scope>|<timing>|<notes>`
- `fresh_audit_report.md` with:
  - `## Scope`
  - `## Inputs Reviewed`
  - `## Criteria Check`
  - `## Findings`
  - `## Result`
  - `Overall: PASS/FAIL`

## Hard Checks
- No unresolved high-severity hazard can be waived implicitly.
- Assumptions must be testable or externally validated.
- Risk/control claims must map to explicit command/test evidence.
- Incremental testing evidence must exist for large/complex tasks (baseline, chunk checks, integration, final validation).
- Long-running tasks must include short plumbing-check evidence before full-length executions.
- Visual PR evidence must use `.png` only when visuals are used.
- Verification must fail if planned PR visualization evidence is missing or not self-reviewed.
- Verification must fail if PR body does not reflect latest validation/evidence status.
- Do not mark gate passing if any required command fails.
- Do not mark gate passing if fresh audit result is `Overall: FAIL`.
- Flag missing logs or mismatched claims as failures.
- Re-run verification and gate pipeline after every feedback-driven code change.
- If feedback changes behavior/interfaces, update verification control mapping before implementation proceeds.

## Stop Conditions
- Missing domain assumption data for risk verification
- Verification does not cover a required control
- Environment cannot reproduce claimed results
- Required command output unavailable
- Validation list is incomplete for changed scope
- Implementation diverges from designed controls/mitigations
