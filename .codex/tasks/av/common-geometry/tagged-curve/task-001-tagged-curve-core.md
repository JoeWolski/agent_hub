# Task Contract: task-001

## Title
Implement `TaggedCurve` core container and typed tag timeline semantics.

## Objective
Add the core `TaggedCurve` API in `av/common/geometry` that can wrap an existing curve and provide typed tag registration, mutation, inclusive evaluation at exact change coordinates, and change-point queries with deterministic ordering.

## Out of Scope
- Nominal-route migration adapters.
- Tracker stage refactors.
- Nominal-route rotational primitive removal.

## Allowed Edit Paths
- av/common/geometry/tagged_curve.hh
- av/common/geometry/CMakeLists.txt
- av/common/geometry/tagged_curve_test.cc
- av/common/geometry/messages.rbuf
- av/common/geometry/conversion.hh
- av/common/geometry/conversion.cc
- av/common/geometry/conversion_test.cc

## Assumptions
- Underlying curve coordinate conversion is deterministic.
- Tag value validators are deterministic and side-effect free.

## Required Tests
- Unit: `av/common/geometry/tagged_curve_test.cc`
- Integration: coordinate parity against `to_arc_length` / `to_normalized` conversions.
- Regression: inclusive change-point boundary behavior (exact boundary, epsilon before, epsilon after).
- Conversion: deterministic rbuf round-trip serialization/deserialization for tagged curves and tag value domains.
- Visualization: expected-vs-observed plots of tag value vs arc length for representative line/polyline/piecewise primitives.

## Required Validation Commands
```bash
./make.sh av_common_geometry_test
./make.sh av_common_geometry_conversion_test
./lint.sh --fast
build/pipelines_simulation_planning_simple 12e7eb72-07cf-4477-9829-f618b10e9f4c
```

## Acceptance Criteria
- [ ] `add_tag` requires initial value and validates it.
- [ ] `set_tag_from` maintains canonical sorted change-point representation.
- [ ] `evaluate_tag`, `next_change`, `previous_change`, and `all_change_points` are implemented and tested.
- [ ] `evaluate_tag` at exact change coordinate is inclusive (returns changed value).
- [ ] Arc-length and normalized queries are parity-tested.
- [ ] `TaggedCurve` rbuf serialization/deserialization round-trip is deterministic and lossless for supported value domains.
- [ ] Unit-test visualization artifacts are generated with expected-vs-observed legends and attached to PR evidence.

## Feedback Updates
- Cycle: design-cycle-1
- Requested change: unified tagged curve with typed evaluation and change-point queries.
- Implementation update: pending implementation phase.

## Failure Modes To Check
- Non-finite coordinates/values are accepted.
- Redundant same-value change points are retained and alter query behavior.
- Exact-change boundary returns previous value instead of new value.
- Rbuf conversion round-trip mutates tag ordering/values or enum encodings.

## Status
Status: COMPLETE
# Allowed values: TODO, IN_PROGRESS, COMPLETE, REVISED_COMPLETE

## Execution Log
```text
command: ./make.sh av_common_geometry_test
result: PASS
notes: Compiled geometry library/tests including new tagged_curve core API and unit suite.

command: AV_TEST_MAKE_IMAGES=1 build/tests/av_common_geometry_test --gtest_filter=TaggedCurveTests.*
result: PASS
notes: Verified inclusive evaluation, change-point queries, coordinate parity, and generated visualization images under build/artifacts/tagged_curve/test_images/.

command: ./make.sh av_common_geometry_conversion_test
result: PASS
notes: Built conversion target after adding tagged-curve rbuf schema/conversion support.

command: AV_TEST_MAKE_IMAGES=1 build/tests/av_common_geometry_conversion_test
result: PASS
notes: Verified deterministic tagged-curve encode/decode round-trip and schema validation behavior.
```

## Remaining Risks
- Tagged-curve rbuf encoding currently supports `double`, `bool`, `string`, and `int32` (including enums/int32-compatible integrals); wider numeric domain support would need explicit schema/version policy.
