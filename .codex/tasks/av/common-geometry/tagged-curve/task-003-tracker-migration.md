# Task Contract: task-003

## Title
Migrate tracker stage consumers to tagged metadata queries.

## Objective
Refactor tracker-stage route metadata reads to consume `TaggedCurve` outputs, reducing bespoke segment-type branching, removing now-dead rotational primitive branches, and centralizing next/previous/all change-point lookup behavior.

## Out of Scope
- New planner control laws.
- Changes to unrelated tracking messages.
- Removal of runtime safeguards not tied to metadata lookup.

## Allowed Edit Paths
- av/planning/tracking/stages/pure_pursuit_planner_stage.cc
- av/planning/tracking/stages/local_trajectory_stage.cc
- av/planning/tracking/CMakeLists.txt
- av/planning/tracking/route_station_benchmark.cc

## Assumptions
- Migration keeps existing stop-point progression semantics.
- Direction and speed constraints remain equivalent to legacy interpretation.

## Required Tests
- Unit: affected tracking unit tests under `av/planning/tracking`.
- Integration: route walk and lookahead progression scenarios used by `route_station_benchmark`.
- Regression: forward/reverse transitions near goal and sub-goal boundaries.
- Visualization: expected-vs-observed tag timeline overlays against walked route station samples, attached as PR artifacts.

## Required Validation Commands
```bash
./make.sh av_planning_tracking_tests
./make.sh av_planning_tracking_route_station_benchmark
./make.sh pipelines_simulation_planning_simple
./lint.sh --fast
build/pipelines_simulation_planning_simple 12e7eb72-07cf-4477-9829-f618b10e9f4c
```

## Acceptance Criteria
- [ ] Tracker stages no longer depend on ad-hoc segment metadata branching where tagged queries can replace it.
- [ ] Goal and sub-goal boundary handling remains deterministic and parity-tested.
- [ ] Benchmark and integration evidence show no regressions in route-station progression behavior.
- [ ] Tracker behavior at exact tag change points is inclusive and parity-tested (evaluate exactly at boundary returns changed value).
- [ ] Visualization artifacts for route/tag progression are generated and attached to PR evidence.

## Feedback Updates
- Cycle: design-cycle-1
- Requested change: support eventual replacement of core mechanics into unified tagged representation.
- Implementation update: pending implementation phase.

## Failure Modes To Check
- Next-stop or goal detection changes due to strict vs inclusive boundary mismatch.
- Reverse-direction handling signs flipped in velocity/heading computations.
- Lookahead extension logic diverges near route end.
- Residual rotational-branch assumptions cause dead code paths or incorrect abort behavior.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./make.sh av_planning_tracking_route_station_benchmark
result: PASS
notes: Rebuilt route-station benchmark after tracker metadata migration and rotational primitive removal.

command: build/av_planning_tracking_route_station_benchmark --output-dir build/artifacts/tagged_curve/benchmarks/route_station
result: PASS
notes: Generated deterministic route-station benchmark JSON/markdown evidence for migration path.

command: ./make.sh pipelines_simulation_planning_simple
result: PASS
notes: Rebuilt end-to-end simulation pipeline including tracking stages migrated to tagged metadata queries.

command: build/pipelines_simulation_planning_simple 12e7eb72-07cf-4477-9829-f618b10e9f4c
result: PASS
notes: Required PR validation command passed with local trajectory stage traversing sub-goals and reaching terminal success.
```

## Remaining Risks
- Tagged metadata queries are currently rebuilt per call-site invocation in tracking stages; performance optimization via route-level cache is a follow-up opportunity if needed.
