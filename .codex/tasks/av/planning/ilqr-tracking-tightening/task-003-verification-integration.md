# Task Contract: task-003

## Title
Verification, adversarial review, and integration artifacts.

## Objective
Generate validation manifest/report, update verification/challenge docs, and provide integration and PR artifacts for the implementation workflow.

## Out of Scope
- Additional behavior changes beyond implemented code.

## Allowed Edit Paths
- docs/av/planning/ilqr-tracking-tightening/*
- .codex/tasks/av/planning/ilqr-tracking-tightening/*

## Assumptions
- Command-level validation is representative for changed modules.

## Required Tests
- Unit: optimization model + iLQR stage tests
- Integration: required policy simulation command and iLQR scenario run
- Regression: lint fast

## Required Validation Commands
```bash
./lint.sh --fast
./make.sh av_optimization_models_bicycle_model_residual_test
./make.sh --run tests/av_optimization_models_bicycle_model_residual_test
./make.sh av_planning_tracking_ilqr_planner_stage_test
./make.sh --run tests/av_planning_tracking_ilqr_planner_stage_test
./make.sh pipelines_simulation_planning_simple
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733 --planner ilqr
tools/codex/autonomous_pr_cycle.sh --run-dir docs/av/planning/ilqr-tracking-tightening
```

## Acceptance Criteria
- [x] Validation manifest and report generated.
- [x] Required command status captured.
- [x] Integration report produced with workstream mapping.

## Feedback Updates
- Cycle: implementation-3
- Requested change: run official implementation workflow and integrate all workstreams.
- Implementation update: generated validation/PR artifacts and merged docs.

## Failure Modes To Check
- Missing required command in manifest.
- Challenge report missing findings section.

## Status
Status: COMPLETE

## Execution Log
```text
command: ./lint.sh --fast
result: PASS
notes: Mandatory fast lint command completed.

command: ~/.local/bin/parquet-tools show ./.av/metrics/metrics:planner_regression_metric.parquet
result: PASS
notes: Metrics extracted; cte_p99 target remains unmet.
```

## Remaining Risks
- `cte_p99_m` remains above target in current tuning state; rollout should remain blocked pending additional objective tuning.
