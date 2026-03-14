# Task Contract: task-002

## Title
Add optional indexed running-term dispatch in iLQR inner solver

## Objective
Allow models to expose `running_cost` and `running_residual` with timestep index, while preserving compatibility with existing non-indexed signatures.

## Out of Scope
- Any change to backward pass numerics beyond call dispatch.

## Allowed Edit Paths
- av/optimization/ilqr/optimizer_autodiff.hh

## Assumptions
- Compile-time dispatch with `if constexpr` preserves deterministic behavior for existing models.

## Required Tests
- Unit: existing iLQR unit tests plus AL tests.
- Integration: N/A.
- Regression: solver/termination/rollout consistency tests.

## Required Validation Commands
```bash
./make.sh av_optimization_ilqr_solver_test
./make.sh --run tests/av_optimization_ilqr_solver_test
./make.sh av_optimization_ilqr_optimizer_termination_test
./make.sh --run tests/av_optimization_ilqr_optimizer_termination_test
```

## Acceptance Criteria
- [x] Existing model APIs continue to compile/run unchanged.
- [x] Indexed signatures are used when available.

## Feedback Updates
- Cycle: 1
- Requested change: AL multipliers must be stage-specific; avoid inner solver duplication.
- Implementation update: Added indexed-running-term dispatch helpers with fallback to legacy signatures in `optimizer_autodiff.hh`.

## Failure Modes To Check
- Incorrect overload resolution causing runtime behavior drift.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./make.sh av_optimization_ilqr_solver_test
result: PASS
notes: baseline solver regression target builds

command: ./make.sh --run tests/av_optimization_ilqr_solver_test
result: PASS
notes: baseline iLQR solver behavior remains valid

command: ./make.sh av_optimization_ilqr_optimizer_termination_test
result: PASS
notes: termination regression target builds

command: ./make.sh --run tests/av_optimization_ilqr_optimizer_termination_test
result: PASS
notes: termination-status regressions remain passing
```

## Remaining Risks
- Subtle template dispatch mistakes can regress objective evaluation.
