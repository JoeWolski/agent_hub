# Task 01: Core SDF Edge Policy

- Agent Type: implementation
- Scope: add explicit raster edge handling modes in `av/common/geometry/sdf/*`.
- Allowed Edit Paths:
  - `av/common/geometry/sdf/sdf2d.hh`
  - `av/common/geometry/sdf/sdf2d.cc`
  - `av/common/geometry/sdf/sdf2d_test.cc`
- Required Validation Commands:
  - `./make.sh av_common_geometry_test`
  - `build/tests/av_common_geometry_test --gtest_filter='Sdf2dTest.raster_sampling_supports_all_interpolation_modes:Sdf2dTest.raster_sampling_edge_mode_constant_value_returns_configured_outside_value:Sdf2dTest.raster_sampling_edge_mode_constant_pos_inf_returns_positive_infinity_outside'`

Status: REVISED_COMPLETE

## Completion Notes
- Added `RasterEdgeMode` with `CLAMP`, `CONSTANT_POS_INF`, and `CONSTANT_VALUE`.
- Extended raster sampling to apply explicit edge policy across nearest/bilinear/bicubic paths with deterministic non-finite handling.
- Added unit tests for constant-value and positive-infinity outside-map behavior.
- Added CUDA-backed rasterization path for baked SDF grids with deterministic CPU fallback when CUDA is unavailable.
- Added NVCC compatibility fixes required by repo-wide generated/message headers and strong-type utilities for CUDA 20 compilation.

## Commands Run
- `./make.sh av_common_geometry_test` : PASS
- `build/tests/av_common_geometry_test --gtest_filter='Sdf2dTest.raster_sampling_supports_all_interpolation_modes:Sdf2dTest.raster_sampling_edge_mode_constant_value_returns_configured_outside_value:Sdf2dTest.raster_sampling_edge_mode_constant_pos_inf_returns_positive_infinity_outside'` : PASS
- `build/tests/av_common_geometry_test --gtest_filter='Sdf2dTest.rasterize_gpu_if_available_matches_cpu_for_baked_source'` : PASS

## Remaining Risks
- Planner-side decode/config plumbing for edge policy is integrated separately in planner workstream.
