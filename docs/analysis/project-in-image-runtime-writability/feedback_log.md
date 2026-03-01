# Feedback Log: Project-In-Image Runtime Writability

## Revision 1 (Initial)
- Captured commit-history analysis for failed prior attempts (`#205`, `#211`, `#214`, `#215`, `#218`).
- Identified primary gap: ownership repair path not guaranteed in hub snapshot build flow.
- Proposed deterministic fix strategy and verification controls.
- Added task contracts with explicit allowed paths and validation commands.
- Added adversarial findings focused on silent regression and insufficient end-to-end coverage.

## Revision 2 (Implementation)
- Implemented hub snapshot command wiring to always pass `project_in_image=True` in setup snapshot builds.
- Refactored CLI ownership repair trigger to follow in-image workspace-copy semantics instead of launch-flag coupling.
- Added runtime UID:GID writability probe before snapshot commit.
- Added regression tests for:
  - hub prepare-snapshot command includes `--project-in-image`,
  - ownership repair + writability probe ordering,
  - prepare-snapshot-only path also enforces repair+probe.
- Captured validation manifest and verification/fresh-audit reports.

## Open Questions
- Whether to add a dedicated real-daemon end-to-end integration test in a follow-up change for chat-start write checks.
