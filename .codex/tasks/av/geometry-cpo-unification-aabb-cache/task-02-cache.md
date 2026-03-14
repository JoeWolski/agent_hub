# Task Contract: TASK-02

## Title
AABB accelerated geometry cache

## Objective
Implement bake + dynamic-update cache with exact nearest queries using AABB lower-bound pruning.
Expand cache API to cover all sensible primitive ops and add visualization-focused tests.

## Out of Scope
- Planner pipeline integration.

## Allowed Edit Paths
- av/common/geometry/aabb_geometry_cache.hh
- av/common/geometry/CMakeLists.txt
- av/common/geometry/aabb_geometry_cache_test.cc

## Assumptions
- R-tree nearest order is monotonic by box lower-bound.

## Required Tests
- Unit: new cache tests for bake/add/remove/move/nearest
- Unit: visualization artifact generation for cache behavior (`AV_TEST_MAKE_IMAGES=1`)
- Integration: N/A
- Regression: existing geometry unit tests

## Required Validation Commands
```bash
./make.sh av_common_geometry_test
./make.sh --run tests/av_common_geometry_test -- --gtest_filter='AABBGeometryCache*'
```

## Acceptance Criteria
- [x] Correctness for nearest distance/projection.
- [x] Dynamic updates maintain consistency.
- [x] Cache supports nearest-k, within-distance, contains, nearest-by-box, and squared-distance queries.
- [x] Visualization-producing tests are present for visualizable cache behavior.

## Feedback Updates
- Cycle: 1
- Requested change: Add bake and dynamic update support with accelerated nearest queries.
- Implementation update: Added `AABBGeometryCache` with bake/add/remove/move/upsert/intersects/nearest APIs and exact nearest stopping rule.

## Failure Modes To Check
- Stale rtree entries after mutation.

## Status
Status: COMPLETE

## Execution Log
```text
command: ./make.sh av_common_geometry_test
result: PASS
notes: Test binary includes new cache tests.

command: ./make.sh --run tests/av_common_geometry_test -- --gtest_filter='AABBGeometryCache*'
result: PASS
notes: 2D/3D cache tests passed.

command: AV_TEST_MAKE_IMAGES=1 ./make.sh --run tests/av_common_geometry_test -- --gtest_filter='AABBGeometryCache.bake_mutation_nearest_k_and_range_queries_2d'
result: PASS
notes: Visualization artifact generated for cache behavior.
```

## Remaining Risks
- Performance sensitivity to query distribution.
