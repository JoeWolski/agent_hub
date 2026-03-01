# Task Contract: {{TASK_ID}}

## Title
{{TITLE}}

## Objective
Describe exactly what this task must deliver.

## Out of Scope
List explicit non-goals.

## Allowed Edit Paths
- path/to/module

## Assumptions
- Assumption A
- Assumption B

## Required Tests
- Unit:
- Integration:
- Regression:

## Required Validation Commands
```bash
# Run minimal targeted checks for changed scope.
uv run pytest tests/<targeted_test>.py
cd web && yarn build
```

## PR Evidence Plan
- Required artifacts:
  - List exact visual artifacts to produce, with owner and path.
- Visualization design:
  - Define each planned visualization before implementation starts.
  - For each visualization, state:
    - expected-vs-observed signal
    - legend contents
    - why it gives an at-a-glance correctness argument
- Self-review gate:
  - Before PR-body inclusion, assert each visual artifact is:
    - clear/readable
    - legend-consistent
    - artifact/bug/glitch free
    - complete for required visualization intent
  - Format preference:
    - `.jpg`/`.jpeg` preferred
    - `.png` only when required

## Incremental Testing Breakdown
- Baseline:
  - Capture baseline behavior (targeted test result and/or key logs) before code edits.
- Compile/Smoke:
  - After first compileable change, run the smallest relevant smoke command.
  - For long-running flows, run a short plumbing check first to verify wiring/output paths before full runs.
- Chunk Validation:
  - After each logical change chunk, run nearest unit/subsystem tests.
- Integration Validation:
  - Run broader integration tests for impacted module boundaries.
- Final Validation:
  - Run required validation commands before marking task complete.
- Diagnostics Discipline:
  - Record each step in `Execution Log` with command, PASS/FAIL, and key failure clues.
  - Do not continue large new edits while earlier incremental checks are failing.
  - Keep PR body updated as validation/evidence status changes.

## Logging and Diagnostics Plan
- Python logging:
  - Use equivalent levels: `logging.error`, `logging.warning`, `logging.info`, `logging.debug`.
  - Add detailed debug traces around failure-prone paths during development/testing.
- Frontend/Node logging:
  - Use established project logging patterns and include sufficient debug context when diagnosing failures.
- Cleanup:
  - Keep durable diagnostics; remove purely temporary noise before final handoff unless explicitly requested.

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Feedback Updates
- Cycle:
- Requested change:
- Implementation update:

## Failure Modes To Check
- Failure mode and mitigation expectation.

## Status
Status: TODO
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: <cmd>
result: <PASS/FAIL>
notes: <details>
```

## Remaining Risks
- Risk after task completion.
