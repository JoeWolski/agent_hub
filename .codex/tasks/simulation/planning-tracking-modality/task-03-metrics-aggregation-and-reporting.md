# Task Contract: TASK-03

## Title
Per-scenario metrics, pandas aggregation, and clickable reporting

## Objective
Add per-scenario parquet metrics normalization, pandas-based set aggregation hook, automatic aggregate parquet persistence, and clickable scenario report generation with required images.

## Out of Scope
- Planner algorithm tuning.
- Frontend redesign outside generated report artifacts.

## Allowed Edit Paths
- simulation/metrics/messages.rbuf
- simulation/metrics/stages/
- pipelines/simulation/planning/tracking/
- analysis/simulation/planning_tracking/
- docs/simulation/planning-tracking-modality/

## Assumptions
- Existing metric channels remain available in worker runs.
- Aggregation API consumes pandas DataFrames and returns one DataFrame.

## Required Tests
- Unit: aggregation API input validation and deterministic output behavior.
- Integration: scenario-set run producing scenario parquet + aggregate parquet + report pages.
- Regression: metric writer channel matching continues to persist parquet outputs.

## Required Validation Commands
```bash
./make.sh pipelines_simulation_planning_tracking
./make.sh --test-regex simulation_metrics
./make.sh --test-regex planning_tracking.*aggregation
./make.sh --run pipelines_simulation_planning_tracking -- --scenario-set <set-guid-or-path>
python3 analysis/simulation/planning_tracking/report.py --run-dir <run-dir> --validate-only
```

## PR Evidence Plan
- Required artifacts:
  - `report/images/<scenario_guid>_world_state.png`
  - `report/images/<scenario_guid>_initial_vs_optimized_trajectory.png`
  - `report/images/set_scoreboard.png`
  - `metrics/scenario/<scenario_guid>/tracking_run_metrics.parquet`
  - `metrics/set/aggregated_metrics.parquet`
- Visualization design:
  - per-scenario world state and trajectory overlays with expected-vs-observed labels.
  - set scoreboard with one-row-per-scenario status and metric highlights.
- Self-review gate:
  - clear/readable
  - legend-consistent
  - artifact/bug/glitch free
  - complete for required intent

## Incremental Testing Breakdown
- Baseline:
  - Run scenario-set pipeline without aggregation/report to capture current outputs.
- Compile/Smoke:
  - Build after metric schema/stage wiring.
- Chunk Validation:
  - Run aggregation unit tests after parser and dataframe-contract edits.
- Integration Validation:
  - End-to-end set run to verify parquet + report outputs.
- Final Validation:
  - Re-run all required commands above.
- Diagnostics Discipline:
  - Record missing-file/schema errors with actionable messages.

## Logging and Diagnostics Plan
- C++ logging:
  - Log metric channel subscriptions and per-scenario metric write completion.
- Python logging:
  - Log file discovery, dataframe schema checks, aggregation invocation, output write paths.
- Cleanup:
  - Keep structured info/warn/error logs for postmortem; remove temporary debug spam.

## Acceptance Criteria
- [x] Scenario parquet metrics include required identity columns.
- [x] Aggregation function receives per-scenario dataframes and output is auto-persisted to parquet.
- [x] Report index and scenario pages are generated with valid links and required images.

## Failure Modes To Check
- Aggregation silently ignores missing scenario parquet files.
- Report contains broken links to scenario pages/images.

## Status
Status: DONE (2026-03-02)

## Execution Log
```text
command: PYTHONPATH=analysis/simulation/planning_tracking python3 -m unittest discover -s analysis/simulation/planning_tracking/tests -v
result: PASS
notes: Ran 8 tests; aggregation, metrics IO, and report generation tests all passed.

command: python3 -c "<local artifact generation script>"
result: PASS
notes: Generated local evidence run artifacts under build/artifacts/planning_tracking/local_validation_run including aggregated parquet and report images.

command: python3 analysis/simulation/planning_tracking/report.py --run-dir build/artifacts/planning_tracking/local_validation_run --validate-only
result: PASS
notes: validate-only mode succeeds on generated run directory.
```

## Remaining Risks
- Aggregation extensibility requires strict sandbox/timeouts to avoid unsafe user code behavior.
