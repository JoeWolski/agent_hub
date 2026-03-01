# Fresh Auditor Agent Contract

## Purpose
Provide an independent implementation-vs-design audit using a brand-new agent context to detect drift after long implementation loops.

## Mandatory Inputs
- `design_spec.md`
- `verification.md`
- `.codex/tasks/analysis/<feature-name>/task-*.md`
- `validation/manifest.txt`
- `verification_report.md`
- Code diff for changed files only

## Context Isolation Rules
- Must run as a newly spawned agent for each audit cycle.
- Must not receive prior implementation conversation history.
- Must not reuse prior reviewer/auditor state.
- Must review only mandatory inputs listed above.

## Required Process
1. Build a checklist from design acceptance criteria and task contracts.
2. Compare implemented diff against checklist and declared non-goals.
3. Verify each claimed validation command exists in manifest/report.
4. Identify mismatches between design intent and actual implementation behavior.
5. Assert PR evidence quality/completeness against planned visualization requirements:
   - visual artifacts used for PR evidence prefer `.jpg`/`.jpeg` (`.png` only when required)
   - required planned visualizations are present
   - each visualization provides at-a-glance correctness support
   - self-review checks were completed (clarity, legend match, no glitches/artifacts)
   - PR body is up to date with latest evidence/validation outcomes
6. Emit deterministic PASS/FAIL with concrete evidence.

## Required Outputs
- `fresh_audit_report.md` including:
  - `## Scope`
  - `## Inputs Reviewed`
  - `## Criteria Check`
  - `## Findings`
  - `## Result`
- Result line at end of report:
  - `Overall: PASS`
  - or `Overall: FAIL`

## Hard Checks
- No PASS if any acceptance criterion lacks evidence mapping.
- No PASS if implementation diverges from approved file ownership.
- No PASS if required validation command evidence is missing.
- No PASS if PR visual evidence format/content/review assertions are incomplete.

## Stop Conditions
- Missing mandatory audit inputs
- Diff unavailable for changed files
- Validation evidence unavailable
