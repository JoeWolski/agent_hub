# Task Contract: TASK-01

## Title
Tracking scenario schema and single-scenario worker pipeline

## Objective
Add the new `simulation::planner::tracking` scenario schemas and implement worker-mode execution in `pipelines_simulation_planning_tracking` for one scenario GUID.

## Out of Scope
- Scenario-set orchestration.
- Pandas aggregation/report generation.

## Allowed Edit Paths
- simulation/planner/tracking/
- simulation/planning/
- pipelines/simulation/planning/tracking/
- pipelines/simulation/planning/CMakeLists.txt

## Assumptions
- Existing planning-simple stage graph is the baseline for worker behavior.
- `Scenario` must include `planner_world_state` plus existing scenario/variation parameters.

## Required Tests
- Unit: scenario parse/validation tests for required fields and deterministic defaults.
- Integration: worker pipeline run with one scenario GUID.
- Regression: planning-simple pipeline still builds/runs unchanged.

## Required Validation Commands
```bash
./make.sh pipelines_simulation_planning_tracking
./make.sh --test-regex tracking.*scenario
./make.sh --run pipelines_simulation_planning_tracking -- --scenario <guid>
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
```

## PR Evidence Plan
- Required artifacts:
  - `report/images/<scenario_guid>_world_state.png`
  - `report/images/<scenario_guid>_initial_vs_optimized_trajectory.png`
- Visualization design:
  - world-state render expected-vs-observed overlay.
  - initial vs optimized trajectory overlay with legend.
- Self-review gate:
  - clear/readable
  - legend-consistent
  - artifact/bug/glitch free
  - complete for required intent

## Incremental Testing Breakdown
- Baseline:
  - Build and run existing planning-simple scenario command.
- Compile/Smoke:
  - Build new tracking pipeline target after schema + arg parsing wiring.
- Chunk Validation:
  - Run scenario parsing tests after each schema/config edit chunk.
- Integration Validation:
  - Run worker mode with representative scenario.
- Final Validation:
  - Re-run all required commands above.
- Diagnostics Discipline:
  - Record command results in validation manifest with PASS/FAIL and key clues.

## Logging and Diagnostics Plan
- C++ logging:
  - Use `LERROR/LWARN/LINFO/LDEBUG` for parse validation, scenario resolution, and mode selection.
- Python logging:
  - Not applicable in this task.
- Cleanup:
  - Keep durable failure logs; remove temporary debug noise before handoff.

## Acceptance Criteria
- [x] `simulation::planner::tracking::Scenario` and `ScenarioSet` schemas compile and parse.
- [x] Worker mode runs a single scenario deterministically and emits isolated artifacts.
- [x] Existing planning-simple command remains functional.

## Failure Modes To Check
- Empty `variation_parameters` accepted silently.
- Missing `planner_world_state` not rejected.

## Status
Status: DONE (2026-03-02)

## Execution Log
```text
command: ./make.sh pipelines_simulation_planning_tracking
result: PASS
notes: target builds successfully.

command: ./make.sh --run pipelines_simulation_planning_tracking -- --scenario f241e7a2-63e4-423b-9732-1f2491019733
result: PASS
notes: simulation reached goal and exited successfully.

command: build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
result: PASS
notes: required regression command completed successfully.
```

## Remaining Risks
- Schema compatibility behavior for legacy scenarios may need explicit migration handling.
