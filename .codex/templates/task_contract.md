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
# Use repo-root wrappers where possible.
./make.sh <target-or-scope>
./make.sh --test-regex <pattern>
```

## PR Evidence Plan
- Required artifacts:
  - List exact `.png` artifacts to produce, with owner and path.
- Visualization design:
  - Define each planned visualization before implementation starts.
  - For each visualization, state:
    - expected-vs-observed signal
    - legend contents
    - why it gives an at-a-glance correctness argument
- Self-review gate:
  - Before PR-body inclusion, assert each `.png` is:
    - clear/readable
    - legend-consistent
    - artifact/bug/glitch free
    - complete for required visualization intent

## Incremental Testing Breakdown
- Baseline:
  - Capture baseline behavior (targeted test result and/or key logs) before code edits.
- Compile/Smoke:
  - After first compileable change, run the smallest relevant smoke command.
  - For simulation/offline-log pipelines, run a short plumbing check first:
    - sim/log time cap: 5 seconds
    - wall-clock cap: 30 seconds
    - verify schema/wiring/output channels/manifest correctness before full runs.
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
- C++ logging:
  - Use `LERROR`, `LWARN`, `LINFO`, `LDEBUG`, and especially `LDEBUG_VERBOSE`.
  - Use `LDEBUG_VERBOSE` liberally with meaningful verbosity levels while developing/debugging.
  - During implementation testing, run with maximum practical log verbosity.
- Python logging:
  - Use equivalent levels: `logging.error`, `logging.warning`, `logging.info`, `logging.debug`.
  - Add detailed debug traces around failure-prone paths during development/testing.
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
