# Deleted Env/Flag Inventory (AOH-05)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Removed env vars
- None confirmed removed in branch diff scope for this cycle.

## Removed CLI flags
- None confirmed removed in branch diff scope for this cycle.

## Behavior changes affecting flags/env
- Explicit `--config-file` and `--system-prompt-file` now fail fast when target files are missing.
- Hub `--log-level` default precedence now uses: explicit flag -> config `logging.level` -> env `AGENT_HUB_LOG_LEVEL` -> `info`.
- Added explicit `--run-mode` override with strict runtime mode contract enforcement.
- `identity.*` config values are now consumed as CLI defaults when explicit local identity flags are absent.
