# Task 03: Integration Regression Coverage

Status: PLANNED

## Objective
Add integration coverage that reproduces hub-managed snapshot build and validates writable project paths in a new chat runtime.

## Allowed Edit Paths
- `tests/integration/*snapshot*`
- `tests/integration/*hub*`
- `src/agent_hub/server.py` (only if needed for testability hooks)
- `docs/analysis/project-in-image-runtime-writability/*`

## Proposed Changes
- Add a deterministic integration scenario that:
  1. builds project snapshot through hub path,
  2. launches new chat with project-in-image,
  3. executes write check under runtime user.
- Capture failure signatures for quick diagnosis.

## Incremental Testing Breakdown
1. Add a short smoke integration check for setup/build path viability.
2. Add writable-check assertion in new chat runtime.
3. Re-run only new integration test.
4. Run integration subset relevant to snapshot launches.

## Required Validation Commands
- `uv run pytest tests/integration/test_snapshot_builds.py -k "project_in_image" -q`
- `uv run pytest tests/integration/test_hub_api_real_process.py -k "chat and snapshot" -q`

## Logging/Diagnostics Plan
- Persist command logs and explicit `Permission denied` pattern checks.
- Print effective UID/GID and file ownership in failing assertions.

## PR Evidence Plan
- Include integration command outputs in `validation/manifest.txt` and summarize in `validation_report.md`.
- No visual evidence required.

## Risks
- Integration tests may be environment-sensitive (daemon/path mapping).
- Mitigation: guard with daemon readiness checks and explicit skips only when prerequisites are absent.
