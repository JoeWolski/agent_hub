# Task 02: CLI Ownership Trigger And Probe

Status: PLANNED

## Objective
Refactor ownership-repair trigger to depend on deterministic snapshot workspace-copy state and add explicit writability probe before snapshot commit.

## Allowed Edit Paths
- `src/agent_cli/cli.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/project-in-image-runtime-writability/*`

## Proposed Changes
- Introduce explicit internal condition representing "repo copied into image workspace".
- Run ownership repair when that condition is true, independent of launch-mode mismatch.
- Add a runtime-user writability probe; fail fast before commit when probe fails.

## Incremental Testing Breakdown
1. Baseline current ownership-repair tests.
2. Add/adjust helper-level tests for trigger condition and probe command behavior.
3. Re-run targeted cli unit tests after each chunk.
4. Run final snapshot-related test subset.

## Required Validation Commands
- `uv run pytest tests/test_hub_and_cli.py -k "repairs_project_ownership" -q`
- `uv run pytest tests/test_hub_and_cli.py -k "snapshot_runtime_project_in_image" -q`

## Logging/Diagnostics Plan
- Record command list with ordering checks (`run` -> `chown` -> probe -> `commit`).
- Ensure failure assertions include stderr/stdout snippet for fast triage.

## PR Evidence Plan
- Include probe success/failure validation entries in `validation/manifest.txt`.
- No visual evidence required.

## Risks
- Extra probe can add latency or break in restricted container images.
- Mitigation: use simple POSIX-safe probe and clear fallback error.
