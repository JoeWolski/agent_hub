# Task Contract: TASK-02

## Title
Scenario-set orchestrator mode and deterministic multi-scenario execution

## Objective
Implement `--scenario-set` mode for `pipelines_simulation_planning_tracking` that runs all set scenarios in deterministic order with per-scenario process isolation and manifest tracking.

## Out of Scope
- Pandas aggregation internals.
- Rich report rendering beyond manifest-level links.

## Allowed Edit Paths
- pipelines/simulation/planning/tracking/
- simulation/planner/tracking/
- simulation/planner/tracking/scenario_sets/

## Assumptions
- Worker mode from TASK-01 is available.
- Sequential execution is acceptable for deterministic v1.

## Required Tests
- Unit: set ordering and `execution_order` validation.
- Integration: two-scenario set run with isolated outputs.
- Regression: worker `--scenario` mode still works.

## Required Validation Commands
```bash
./make.sh pipelines_simulation_planning_tracking
./make.sh --test-regex tracking.*scenario_set
./make.sh --run pipelines_simulation_planning_tracking -- --scenario-set <set-guid-or-path>
```

## PR Evidence Plan
- Required artifacts:
  - `report/images/set_scoreboard.png`
  - `report/index.html`
- Visualization design:
  - set scoreboard includes one row per scenario with expected-vs-observed status/metrics.
- Self-review gate:
  - clear/readable
  - legend-consistent
  - artifact/bug/glitch free
  - complete for required intent

## Incremental Testing Breakdown
- Baseline:
  - Run worker mode command from TASK-01.
- Compile/Smoke:
  - Build pipeline after CLI + orchestrator skeleton.
- Chunk Validation:
  - Run ordering tests after sorting/validation changes.
- Integration Validation:
  - Run two-scenario set and verify per-scenario artifact roots.
- Final Validation:
  - Re-run required commands above.
- Diagnostics Discipline:
  - Preserve per-scenario exit codes and failure reasons in manifest.

## Logging and Diagnostics Plan
- C++ logging:
  - Log deterministic order, scenario start/end, exit codes, and failure reasons.
- Python logging:
  - Not applicable in this task.
- Cleanup:
  - Avoid verbose per-tick logs in orchestrator path.

## Acceptance Criteria
- [x] `--scenario-set` executes all scenarios exactly once in deterministic order.
- [x] Per-scenario artifact roots are isolated by `run_id/scenario_guid`.
- [x] Manifest includes ordered GUID list and per-scenario status.

## Failure Modes To Check
- Scenario omitted silently from run.
- Duplicate scenario execution from malformed `execution_order`.

## Status
Status: DONE (2026-03-02)

## Execution Log
```text
command: ./make.sh --test-regex 'tracking.*scenario_set'
result: PASS
notes: simulation_planner_tracking_scenario_set_test passed.

command: ./make.sh --run pipelines_simulation_planning_tracking -- --scenario-set simulation/planner/tracking/scenario_sets/smoke.yml
result: PASS
notes: scenario-set mode executed deterministically and generated .av/planning_tracking_run_manifest.yml.
```

## Remaining Risks
- Long scenario sets may require future parallelization policy and resource controls.
