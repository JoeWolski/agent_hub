# Task Contract: TASK-01

## Title
Primitive CPO unification layer

## Objective
Implement CPO adapters so `aabb` and point-query operations can be called uniformly across supported primitives.
Ensure public header APIs are fully documented with Doxygen-style comments and non-trivial logic is sensibly commented.

## Out of Scope
- Rewriting all consumers.

## Allowed Edit Paths
- av/common/geometry/curve_ops.hh
- av/common/geometry/primitive_ops.hh
- av/common/geometry/point.hh
- av/common/geometry/circle.hh
- av/common/geometry/polygon.hh

## Assumptions
- Existing primitive math is authoritative.
- CPO additions are additive and non-breaking.

## Required Tests
- Unit: av/common/geometry tests for primitive ops
- Integration: N/A
- Regression: existing geometry tests

## Required Validation Commands
```bash
./make.sh av_common_geometry_test
./make.sh --run tests/av_common_geometry_test -- --gtest_filter='PrimitiveOps*:*AABBGeometryCache*'
```

## Acceptance Criteria
- [x] Point-query CPOs compile and work for supported primitives.
- [x] `aabb(primitive)` covers additional primitives.
- [x] Added primitive ops are documented (`@brief`, `@param`, `@return`) and comments are clear.

## Feedback Updates
- Cycle: 1
- Requested change: CPO-first primitive unification and deduplicated query APIs.
- Implementation update: Added `primitive_ops.hh`, added primitive `aabb` adapters, added projection/distance CPOs, generalized CPO dispatch in `curve_ops.hh`.

## Failure Modes To Check
- Incorrect projection semantics.

## Status
Status: COMPLETE

## Execution Log
```text
command: ./make.sh av_common_geometry_test
result: PASS
notes: Build succeeded after adding new headers and test integration.

command: ./make.sh --run tests/av_common_geometry_test -- --gtest_filter='PrimitiveOps*:*AABBGeometryCache*'
result: PASS
notes: PrimitiveOps tests passed.

command: ./make.sh av_common_geometry_test
result: PASS
notes: Rebuilt after documentation and primitive-op expansion updates.
```

## Remaining Risks
- Additional primitives may need custom tag_invoke overloads.
