# Startup Reconcile Best-Effort Orphan Cleanup

## Status

SPEC COMPLETE

## Goal

Prevent Agent Hub startup reconciliation from crashing its background thread when orphaned chat, project, temp, or log paths cannot be deleted. Orphan cleanup must be best-effort: log the failure, keep startup reconcile running, and leave the server usable.

## Non-Goals

- Do not change which paths are considered managed versus orphaned.
- Do not silently suppress runtime-state reconciliation errors unrelated to orphan cleanup.
- Do not add retries, chmod/chown mutations, or destructive fallback deletion strategies.

## Scope

- Add a best-effort orphan deletion helper to `LifecycleService.startup_reconcile(...)`.
- Use it for orphan chat workspaces, artifacts, project workspaces, project temp roots, per-project temp children, and orphan logs.
- Ensure startup reconcile returns a normal summary even when some orphan deletions fail.
- Catch and log unexpected startup reconcile worker failures so the background thread does not emit an unhandled traceback.
- Add focused regression coverage for an orphan deletion failure.

## Acceptance Criteria

- If deleting one orphan filesystem entry raises `HTTPException`, startup reconcile must:
  - log a warning that includes the path and failure detail
  - continue processing the remaining orphan entries
  - still return a summary dict
  - not propagate the exception to the caller
- Successfully deleted orphans must still count toward the existing `removed_orphan_*` summary fields.
- Failed deletions must leave the path in place.
- `HubState._startup_reconcile_worker(...)` must log unexpected failures via `LOGGER.exception(...)` instead of allowing an unhandled thread traceback.

## Class Inventory

- `LifecycleService`
  - `startup_reconcile(...) -> dict[str, int]`
- `HubStateRuntimeMixin`
  - `_remove_orphan_children(..., ignore_delete_errors: bool = False, orphan_kind: str = "path") -> int`
  - `_remove_orphan_log_entries(..., ignore_delete_errors: bool = False) -> int`
  - `_startup_reconcile_worker(self) -> None`

## Interfaces And Data

- The best-effort helpers must preserve the existing summary shape:
  - `removed_orphan_chat_paths`
  - `removed_orphan_project_paths`
  - `removed_orphan_log_entries`
- Failed deletions are reported only through logs, not by changing the summary schema.
- The warning log must include enough context to identify which orphan path could not be deleted.

## Error Model

- Expected orphan-cleanup failures (`HTTPException` raised from `_delete_fs_entry(...)`) are downgraded to warning logs.
- Unexpected exceptions in `_startup_reconcile_worker(...)` are logged with a traceback and stop that worker cleanly.

## Concurrency Model

- Startup reconcile remains single-threaded per scheduled worker.
- Best-effort cleanup does not change lock behavior or startup scheduling.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/services/lifecycle_service.py`](/home/joew/projects/agent_hub/src/agent_hub/services/lifecycle_service.py)
  - [`src/agent_hub/server_hubstate_runtime_mixin.py`](/home/joew/projects/agent_hub/src/agent_hub/server_hubstate_runtime_mixin.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Keep the change narrow and limited to startup cleanup robustness.

## Verification Plan

- Run the new regression in isolation and keep it under 1 second:
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_startup_reconcile_skips_orphan_delete_failures`
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_startup_reconcile_worker_logs_exception`
- Run the focused startup reconcile slice:
  - `uv run python -m pytest tests/test_hub_and_cli.py -k "startup_reconcile_resets_orphaned_chat_runtime_and_removes_orphan_paths or startup_reconcile_marks_starting_chat_failed_when_pid_is_missing or startup_reconcile_skips_orphan_delete_failures or startup_reconcile_worker_logs_exception"`

## PR Evidence Plan

- No UI evidence required because this is backend lifecycle cleanup.

## Ambiguity Register

- “Best-effort” means continue after filesystem cleanup failures while preserving warning visibility; it does not mean silently ignoring all reconcile failures.
