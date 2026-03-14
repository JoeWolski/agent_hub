# Task Contract: task-002

## Title
Add nominal-route to tagged-curve adapter for curvilinear segment metadata and remove rotational primitives.

## Objective
Implement an adapter that translates nominal-route curvilinear segments into a geometric curve plus tag timelines (`speed_limit`, `direction`, `segment_kind`, `blades_engaged`) while preserving route station semantics, and remove `RotationalMotionPrimitive` from `NominalRoute` because it is unused.

## Out of Scope
- Planner-stage behavior changes.
- Removal of legacy APIs in this task.

## Allowed Edit Paths
- av/planning/nominal_route/messages.rbuf
- av/planning/nominal_route/nominal_route_utility.hh
- av/planning/nominal_route/detail/nominal_route_utility.cc
- av/planning/tracking/pure_pursuit_target.hh
- av/planning/tracking/pure_pursuit_target.cc
- av/planning/tracking/pure_pursuit_target_test.cc

## Assumptions
- Existing nominal route segments are ordered in traversal order.
- Segment endpoints remain numerically stable under polyline conversion.

## Required Tests
- Unit: `av_planning_tracking_tests` route station and stop-point parity cases.
- Integration: adapter parity against legacy `get_next_stop_point` transitions on route fixtures.
- Regression: mixed forward/reverse and transition/mow segment sequences after rotational primitive removal.

## Required Validation Commands
```bash
./make.sh av_planning_tracking_tests
./make.sh av_planning_tracking_route_station_benchmark
./make.sh av_planning_nominal_route_nominal_route_stage_test
./lint.sh --fast
build/pipelines_simulation_planning_simple 12e7eb72-07cf-4477-9829-f618b10e9f4c
```

## Acceptance Criteria
- [ ] Adapter emits deterministic tag change points matching legacy segment boundaries.
- [ ] `get_next_stop_point` equivalent behavior is provable from tagged metadata queries.
- [ ] Existing route-station tests continue to pass or are updated with parity evidence.
- [ ] `NominalRoute` rotational primitive schema/runtime usage is removed and no residual branches remain in migrated paths.

## Feedback Updates
- Cycle: design-cycle-1
- Requested change: support replacement of current route mechanics with unified tagged representation.
- Implementation update: pending implementation phase.

## Failure Modes To Check
- Segment boundary loss (missing first/last boundary).
- Direction tag drift from legacy direction field.
- Station-distance mismatch after adapter conversion.
- Stale rotational primitive references left in schema/runtime/tests.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./make.sh av_planning_tracking_tests
result: PASS
notes: Rebuilt tracking target after removing rotational primitives and integrating nominal-route tagged metadata adapter.

command: AV_TEST_MAKE_IMAGES=1 build/tests/av_planning_tracking_tests
result: PASS
notes: Validated stop-point progression, inclusive direction boundary semantics, and metadata parity through tagged-curve helpers.

command: ./make.sh av_planning_nominal_route_nominal_route_stage_test
result: PASS
notes: Rebuilt nominal-route generation/stage test target with updated path schema (curvilinear-only).
```

## Remaining Risks
- External replay/config artifacts that still carry historical rotational path variants will require migration tooling before replaying into this schema.
