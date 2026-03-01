# Verification Report: Project-In-Image Runtime Writability (Re-land)

## Scope
Validate that snapshot prepare/build flow enforces writable in-image workspace deterministically and no longer fails on post-setup `docker exec` against a stopped container.

## Inputs Reviewed
- `src/agent_cli/cli.py`
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/project-in-image-runtime-writability/validation/manifest.txt`
- `docs/analysis/project-in-image-runtime-writability/validation/validation_report.md`

## Findings
- Ownership repair moved into snapshot bootstrap script, executed before container exit, eliminating the stopped-container `docker exec` failure class.
- Bootstrap for copied-in-image snapshots runs as root but executes project setup script as runtime UID/GID via `setpriv`, then repairs ownership and probes writability as runtime user.
- Hub prepare-snapshot command now explicitly sets `--project-in-image`.
- Snapshot schema version is now `8`, invalidating snapshots from both pre-fix and reverted-v7 windows.

## Command Evidence Summary
- Targeted and slice tests: PASS.
- Live API build trigger: PASS (cached snapshot reuse in running service).

## Result
Overall: PASS
