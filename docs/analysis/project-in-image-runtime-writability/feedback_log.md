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
