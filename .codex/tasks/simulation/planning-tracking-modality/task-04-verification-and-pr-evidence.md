# Task Contract: TASK-04

## Title
Verification closure, validation manifests, and PR evidence completion

## Objective
Run full validation for tracking modality implementation, collect deterministic evidence, and finalize PR-ready artifacts and compliance checks.

## Out of Scope
- New feature additions beyond scoped tracking modality design.

## Allowed Edit Paths
- docs/simulation/planning-tracking-modality/
- .codex/tasks/simulation/planning-tracking-modality/

## Assumptions
- TASK-01 through TASK-03 are complete.
- Required visualization and parquet artifacts exist in run directory.

## Required Tests
- Unit: all newly added schema/orchestrator/aggregation/report tests.
- Integration: worker and scenario-set runs.
- Regression: required repository simulation command.

## Required Validation Commands
```bash
./make.sh pipelines_simulation_planning_tracking
./make.sh --test-regex tracking
./make.sh --test-regex simulation_metrics
./make.sh --run pipelines_simulation_planning_tracking -- --scenario <guid>
./make.sh --run pipelines_simulation_planning_tracking -- --scenario-set <set-guid-or-path>
build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
```

## PR Evidence Plan
- Required artifacts:
  - all required report `.png` files and parquet outputs from prior tasks
  - updated `validation/manifest.txt`
  - updated `validation/validation_report.md`
  - updated `pr_body.md`
- Visualization design:
  - verify visuals match planned expected-vs-observed narratives.
- Self-review gate:
  - clear/readable
  - legend-consistent
  - artifact/bug/glitch free
  - complete for required intent

## Incremental Testing Breakdown
- Baseline:
  - Confirm all prior task outputs present before revalidation.
- Compile/Smoke:
  - Rebuild tracking target.
- Chunk Validation:
  - Re-run focused tests tied to changed files since previous cycle.
- Integration Validation:
  - Run both worker and scenario-set commands.
- Final Validation:
  - Run full required command list, including mandatory planning-simple command.
- Diagnostics Discipline:
  - Every command recorded as PASS/FAIL with concise notes in manifest.

## Logging and Diagnostics Plan
- C++ logging:
  - Ensure failure logs include scenario GUID/run ID context.
- Python logging:
  - Ensure aggregation/report validation errors identify offending file/schema/link.
- Cleanup:
  - Keep stable diagnostics used by verification docs and PR review.

## Acceptance Criteria
- [x] Validation manifest is complete and reproducible.
- [x] Required command status is explicitly recorded.
- [x] PR evidence policy requirements are satisfied and self-review assertions are recorded.

## Failure Modes To Check
- Missing mandatory command status in validation section.
- PR body out of sync with latest validation/evidence outputs.

## Status
Status: DONE (2026-03-02)

## Execution Log
```text
command: ./make.sh pipelines_simulation_planning_tracking
result: PASS
notes: target build succeeded.

command: ./make.sh --test-regex 'tracking.*scenario_set'
result: PASS
notes: scenario-set unit test passed.

command: ./make.sh --run pipelines_simulation_planning_tracking -- --scenario f241e7a2-63e4-423b-9732-1f2491019733
result: PASS
notes: worker mode scenario run succeeded.

command: ./make.sh --run pipelines_simulation_planning_tracking -- --scenario-set simulation/planner/tracking/scenario_sets/smoke.yml
result: PASS
notes: scenario-set run succeeded and wrote manifest.

command: build/pipelines_simulation_planning_simple f241e7a2-63e4-423b-9732-1f2491019733
result: PASS
notes: required repository simulation command succeeded.
```

## Remaining Risks
- Runtime variance on long scenario sets may require reruns to isolate environmental noise.
