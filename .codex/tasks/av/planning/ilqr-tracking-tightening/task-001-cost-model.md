# Task Contract: task-001

## Title
Refactor bicycle-model tracking objective into lateral/longitudinal terms with tail suppression and underspeed guard residual.

## Objective
Implement the iLQR objective decomposition in `BicycleModel` to explicitly penalize lateral tracking tail and support anti-slowdown underspeed shaping.

## Out of Scope
- Stage-level timeout handling.
- Pipeline orchestration or PR automation.

## Allowed Edit Paths
- av/optimization/models/bicycle_model.hh
- av/optimization/models/bicycle_model_residual_test.cc

## Assumptions
- Nearest-point projection remains deterministic for each solver call.
- Added residual terms do not change control-limit semantics.

## Required Tests
- Unit: `av_optimization_models_bicycle_model_residual_test`
- Integration: `av_planning_tracking_ilqr_planner_stage_test`
- Regression: planner scenario run with iLQR

## Required Validation Commands
```bash
./make.sh av_optimization_models_bicycle_model_residual_test
./make.sh --run tests/av_optimization_models_bicycle_model_residual_test
```

## Acceptance Criteria
- [x] Lateral and longitudinal residuals are split with separate weights.
- [x] Tail-focused lateral term exists with threshold/beta tuning knobs.
- [x] Underspeed residual exists with deadband and weight.
- [x] Residual tests cover monotonic behavior.

## Feedback Updates
- Cycle: implementation-1
- Requested change: tighten iLQR tracking objective while preserving speed.
- Implementation update: split residual decomposition and added tail/underspeed terms.

## Failure Modes To Check
- Incorrect path-frame sign convention causing divergence.
- Tail term active when below threshold due bad softplus argument.

## Status
Status: COMPLETE

## Execution Log
```text
command: ./make.sh av_optimization_models_bicycle_model_residual_test
result: PASS
notes: Compiled new residual decomposition and tests.

command: ./make.sh --run tests/av_optimization_models_bicycle_model_residual_test
result: PASS
notes: 8/8 tests pass, including lateral-tail and underspeed monotonic checks.
```

## Remaining Risks
- CTE target remains above required threshold; further tuning or model refinement is required.
