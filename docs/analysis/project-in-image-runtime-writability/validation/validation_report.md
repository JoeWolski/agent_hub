# Validation Report: Project-In-Image Runtime Writability (Re-land)

## Scope
Re-implement reverted PR #220 behavior while fixing the deterministic build break in snapshot prepare flow (`docker exec ... container is not running`).

## Commands Executed
See `validation/manifest.txt` for exact commands and PASS results.

## Acceptance Criteria Mapping
- AC: Hub snapshot build path enables project-in-image semantics.
  - Evidence: `test_ensure_project_setup_snapshot_builds_once` now asserts `--project-in-image` is included for prepare-snapshot-only builds.
- AC: Snapshot prepare flow does not depend on post-exit `docker exec` repair.
  - Evidence: `test_snapshot_runtime_project_in_image_repairs_project_ownership_before_commit` asserts ownership repair and writable probe are embedded in bootstrap shell script and no `docker exec` commands are issued.
- AC: Snapshot prepare-only + project-in-image remains valid and avoids bind mounting project checkout.
  - Evidence: `test_snapshot_prepare_only_allows_project_in_image_without_bind_mount` passes.
- AC: Snapshot invalidation covers reverted-v7 window.
  - Evidence: `_snapshot_schema_version()` bumped to `8`.

## Runtime Verification Notes
- A live project-build trigger was executed against the active Hub API for project `28edad7d018f47a0989f00f93b9896d4` (same UI project config).
- The active hub instance returned `ready` and `Using cached setup snapshot image ...`; it did not rebuild an uncached snapshot in that running service process.
- Added daemon-visible mount source rewrite for local `/workspace/tmp/*` paths via `AGENT_HUB_TMP_HOST_PATH` in `agent_cli`.
- Executed uncached end-to-end `agent_cli --prepare-snapshot-only --project-in-image` run successfully with tag `agent-hub-setup-uncached-1772394861`, including snapshot bootstrap ownership repair and writable probe.

## Result
PASS for required code-level, command-construction, and uncached end-to-end snapshot-prepare validation.
