# Task Contract: task-001

## Title
Implement AL-iLQR outer loop wrapper over existing iLQR solver

## Objective
Add a reusable AL-iLQR solver wrapper that composes inner unconstrained iLQR solves with multiplier/penalty updates for running and terminal constraints.

## Out of Scope
- Planner stage integration.
- Quaternion-specific dynamics handling.

## Allowed Edit Paths
- av/optimization/ilqr/augmented_lagrangian_ilqr.hh
- av/optimization/ilqr/CMakeLists.txt

## Assumptions
- Inner iLQR termination status is authoritative for inner-solve failures.
- Constraint functions return finite values on feasible trajectories.

## Required Tests
- Unit: AL equality/inequality convergence behavior.
- Integration: N/A.
- Regression: iLQR solver baseline test target.

## Required Validation Commands
```bash
./make.sh av_optimization_ilqr_augmented_lagrangian_ilqr_test
./make.sh --run tests/av_optimization_ilqr_augmented_lagrangian_ilqr_test
```

## Acceptance Criteria
- [x] Outer loop delegates all unconstrained solve steps to `OptimizerAutoDiff`.
- [x] Equality/inequality multiplier updates are implemented.
- [x] Result includes AL termination metadata.

## Feedback Updates
- Cycle: 1
- Requested change: Implement AL-iLQR from paper tutorial using existing iLQR inner solver.
- Implementation update: Added `augmented_lagrangian_ilqr.hh` with AL outer loop, multiplier projection, penalty scaling, and inner iLQR reuse.

## Failure Modes To Check
- Outer loop false success with unresolved constraint violation.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./make.sh av_optimization_ilqr_augmented_lagrangian_ilqr_test
result: PASS
notes: AL solver wrapper and test target compile

command: ./make.sh --run tests/av_optimization_ilqr_augmented_lagrangian_ilqr_test
result: PASS
notes: terminal-equality and running-inequality constrained tests pass
```

## Remaining Risks
- Penalty schedule may require tuning for highly nonlinear constraints.
