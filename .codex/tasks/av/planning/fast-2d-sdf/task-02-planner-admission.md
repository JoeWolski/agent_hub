# Task 02: Planner SDF Admission and Required Policy

- Agent Type: implementation
- Scope: harden SDF raster admission and fail-safe behavior in iLQR planner stage.
- Allowed Edit Paths:
  - `av/planning/tracking/stages/ilqr_planner_stage.cc`
  - `av/planning/tracking/stages/ilqr_planner_stage_test.cc`
  - `av/planning/tracking/stages/ilqr_planner_stage_config.rbuf`
  - `av/planning/tracking/stages/ilqr_planner_stage_config.yml`
  - `av/common/geometry/messages.rbuf`
- Required Validation Commands:
  - `./make.sh av_planning_tracking_ilqr_planner_stage_test`
  - `build/tests/av_planning_tracking_ilqr_planner_stage_test --gtest_filter='IlqrPlannerStage.sdf_enabled_with_raster_preserves_runtime_trajectory_contract:IlqrPlannerStage.sdf_required_policy_missing_raster_preserves_runtime_trajectory_contract:IlqrPlannerStage.sdf_required_policy_frame_mismatch_preserves_runtime_trajectory_contract'`

Status: COMPLETE

## Completion Notes
- Added planner config knobs for required-policy, frame/age gating, interpolation and edge options, backend preference, and dynamic-layer placeholders.
- Added raster decode admission checks and stage-local metadata tracking.
- Implemented fail-safe required-policy fallback sampler to avoid fail-open obstacle cost behavior when raster is unusable.
- Added planner-stage tests for missing-raster and frame-mismatch required-policy paths.

## Commands Run
- `./make.sh av_planning_tracking_ilqr_planner_stage_test` : PASS
- `build/tests/av_planning_tracking_ilqr_planner_stage_test --gtest_filter='IlqrPlannerStage.sdf_enabled_with_raster_preserves_runtime_trajectory_contract:IlqrPlannerStage.sdf_required_policy_missing_raster_preserves_runtime_trajectory_contract:IlqrPlannerStage.sdf_required_policy_frame_mismatch_preserves_runtime_trajectory_contract'` : PASS

## Remaining Risks
- Required-policy fallback currently enforces fail-safe costing but does not yet expose explicit telemetry counters for rejection reasons.
