# Validation Report: Project-In-Image Runtime Writability

## Scope
Implementation validation for hub snapshot-build command wiring and CLI ownership+writability enforcement in project-in-image snapshot flows.

## Acceptance Criteria Mapping
- AC1: Freshly built project snapshot used by a new chat allows runtime-user writes under container project path.
  - Evidence: ownership repair and runtime UID:GID writable probe are both executed before commit.
- AC2: Ownership/writability failure path blocks commit.
  - Evidence: commit is sequenced after repair + probe in command-order tests.
- AC3: Hub snapshot-build path always opts into project-in-image semantics.
  - Evidence: `_ensure_project_setup_snapshot` now emits `--project-in-image` under `--prepare-snapshot-only`.
- AC4: Previously built broken snapshots are invalidated.
  - Evidence: snapshot schema version incremented to force fresh snapshot tags.

## Commands
See `validation/manifest.txt` for exact command list with PASS/FAIL.

## Results
- Feature-scoped required commands: PASS.
- Diagnostic broader snapshot scan: FAIL due pre-existing `/tmp` daemon-visibility constraints in unrelated tests.

## Residual Risks
- No new real-daemon integration test added in this change; behavior is validated via unit-level command construction and sequencing assertions.
