# Task Contract: task-002

## Title
Expose iLQR objective weights in stage config and enforce 100ms solver timeout kill behavior.

## Objective
Plumb cost weights through `IlqrPlannerStageConfig` and add per-solve timeout guard that logs an error and fails fast when iLQR solve exceeds 100ms.

## Out of Scope
- Multi-scenario tuning rollout.
- Nominal route generator performance fixes.

## Allowed Edit Paths
- av/planning/tracking/stages/ilqr_planner_stage.cc
- av/planning/tracking/stages/ilqr_planner_stage_config.rbuf
- av/planning/tracking/stages/ilqr_planner_stage_config.yml

## Assumptions
- Throwing from solve callback is treated as fatal pipeline failure.
- Timeout threshold of 100ms is an explicit hang policy, not a soft warning.

## Required Tests
- Unit: `av_planning_tracking_ilqr_planner_stage_test`
- Integration: iLQR planner scenario
- Regression: required policy command

## Required Validation Commands
```bash
./make.sh av_planning_tracking_ilqr_planner_stage_test
./make.sh --run tests/av_planning_tracking_ilqr_planner_stage_test
./make.sh pipelines_simulation_planning_simple
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733 --planner ilqr
```

## Acceptance Criteria
- [x] New tracking/heading/speed-floor weights are configurable in stage config.
- [x] Per-solve timeout of 100ms logs `LERROR` and throws runtime error.
- [x] iLQR stage tests pass with the timeout integration.

## Feedback Updates
- Cycle: implementation-2
- Requested change: kill the pipeline on optimization calls taking over 100ms.
- Implementation update: asynchronous solve watchdog with 100ms limit and fatal throw.

## Failure Modes To Check
- Timeout guard deadlocks or blocks destruction path.
- Solver state corruption across async boundary.

## Status
Status: COMPLETE

## Execution Log
```text
command: ./make.sh --run tests/av_planning_tracking_ilqr_planner_stage_test
result: PASS
notes: Both iLQR stage tests pass after timeout/config integration.

command: timeout 120s build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733 --planner ilqr
result: PASS
notes: Pipeline completed successfully within timeout; no IlqrPlannerStage >10s warning observed.
```

## Remaining Risks
- Initial `NominalRouteStage` startup exceeds 10s in this scenario; per strict hang policy this remains a pipeline-level risk outside iLQR solve path.
