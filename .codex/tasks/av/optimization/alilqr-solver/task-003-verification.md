# Task Contract: task-003

## Title
Validate AL-iLQR implementation and produce evidence artifacts

## Objective
Execute required build/tests/lint and required policy pipeline command; capture outcomes in workflow docs.

## Out of Scope
- PR artifact upload to external object store in this task; handled at PR stage if required.

## Allowed Edit Paths
- docs/av/optimization/alilqr-solver/verification_report.md
- docs/av/optimization/alilqr-solver/integration_report.md
- docs/av/optimization/alilqr-solver/validation/manifest.txt
- docs/av/optimization/alilqr-solver/validation/validation_report.md
- docs/av/optimization/alilqr-solver/pr_body.md
- .codex/tasks/av/optimization/alilqr-solver/task-003-verification.md

## Assumptions
- Wrapper validation commands are sufficient for changed scope in `av/optimization/ilqr`.

## Required Tests
- Unit: AL and iLQR regression tests.
- Integration: required planning pipeline command.
- Regression: lint fast pass.

## Required Validation Commands
```bash
./make.sh av_optimization_ilqr_augmented_lagrangian_ilqr_test
./make.sh --run tests/av_optimization_ilqr_augmented_lagrangian_ilqr_test
./make.sh av_optimization_ilqr_solver_test
./make.sh --run tests/av_optimization_ilqr_solver_test
./make.sh av_optimization_ilqr_optimizer_termination_test
./make.sh --run tests/av_optimization_ilqr_optimizer_termination_test
./lint.sh --fast
./make.sh pipelines_simulation_planning_simple
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
```

## Acceptance Criteria
- [x] Validation manifest records command-level pass/fail.
- [x] Verification/integration reports summarize evidence and residual risks.

## Feedback Updates
- Cycle: 1
- Requested change: Run official workflow and implement AL-iLQR.
- Implementation update: Added validation manifest/report inputs, verification report, integration report, and PR body with required sections.

## Failure Modes To Check
- Required pipeline command missing from evidence.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./lint.sh --fast
result: PASS
notes: repo fast lint completed

command: ./make.sh pipelines_simulation_planning_simple
result: PASS
notes: required planning pipeline binary built

command: build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
result: PASS
notes: Goal reached; simulation completed successfully
```

## Remaining Risks
- Long-running pipeline command may be environment-sensitive.
