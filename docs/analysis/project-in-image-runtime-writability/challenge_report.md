# Challenge Report: Project-In-Image Runtime Writability

## Findings
- [HIGH] Ownership repair is currently coupled to `project_in_image` flag in CLI build path, but hub project snapshot builds use `prepare_snapshot_only` without setting that flag. Result: snapshots can be published without ownership repair.
- [HIGH] Existing tests assert command pieces in isolation but do not prove end-to-end writability in the hub-managed snapshot->new-chat path.
- [MEDIUM] Snapshot schema bump mitigates stale image reuse only when build metadata changes are correctly integrated; if ownership semantics drift without schema update, stale broken snapshots can remain.
- [MEDIUM] Current evidence relies heavily on command presence (`chown` exists) rather than outcome validation (runtime user can actually write).

## Reproduction
1. Build snapshot through hub project setup path (`prepare_snapshot_only=True`).
2. Start new chat that uses that snapshot with `--project-in-image`.
3. In chat runtime, attempt `touch /workspace/<project>/.write-test`.
4. Observe intermittent/consistent `Permission denied` when ownership was not repaired at build time.

## Suggested Fixes
- Pass explicit in-image workspace mode during project snapshot build command creation in hub.
- Trigger ownership repair based on snapshot workspace copy mode, not only launch mode.
- Add pre-commit writability probe under runtime UID/GID.
- Add integration test that checks write success in fresh chat from hub-built snapshot.

## Residual Concerns
- User namespace remapping and host daemon differences can still affect UID/GID semantics.
- Cross-environment reproducibility requires explicit daemon/path preflight checks in integration tests.
