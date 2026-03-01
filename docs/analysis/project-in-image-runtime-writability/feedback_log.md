# Feedback Log: Project-In-Image Runtime Writability

## Revision 1 (Initial)
- Captured commit-history analysis for failed prior attempts (`#205`, `#211`, `#214`, `#215`, `#218`).
- Identified primary gap: ownership repair path not guaranteed in hub snapshot build flow.
- Proposed deterministic fix strategy and verification controls.
- Added task contracts with explicit allowed paths and validation commands.
- Added adversarial findings focused on silent regression and insufficient end-to-end coverage.

## Open Questions
- Should ownership be normalized to hub-local UID/GID only, or configurable per project/chat profile for mixed-user environments?
- Should snapshot schema be incremented again as part of final implementation to guarantee invalidation in all deployed states?

## 2026-03-01: Re-land after revert + schema v8 update
- Re-landed snapshot writability implementation without post-exit docker exec.
- Moved ownership repair and writable probe into bootstrap script sequence.
- Explicitly re-enabled `project_in_image=True` for hub snapshot prepare commands.
- Bumped snapshot schema version from 7 -> 8 per revert-window invalidation requirement.
- Added regression tests and updated validation/gates artifacts.
