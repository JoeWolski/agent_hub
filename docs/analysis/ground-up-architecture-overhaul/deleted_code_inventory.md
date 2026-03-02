# Deleted Code Inventory (AOH-05)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Removed/Consolidated Branches and Helpers
- Removed `_LEGACY_PROVIDER_DEFAULT_KEYS` merge logic in `src/agent_core/config/__init__.py`.
- Removed CLI config-file parsing fallback path that attempted JSON-or-TOML parsing for shared prompt context from raw text.
- Removed inlined hub settings normalization/update helpers from `src/agent_hub/server.py` after extraction into `SettingsService`.
- Removed unsupported-provider fallback branch from `src/agent_cli/providers.py::get_provider`.
- Removed unsupported-agent-command fallback branch from `src/agent_cli/cli.py::_agent_provider_for_command`.
- Removed snapshot launch-profile runtime-image exception fallback branch from `src/agent_hub/server.py`.
- Removed non-strict chat `agent_type` state/input normalization in runtime-critical paths.

## Net Effect
- Fewer compatibility fallbacks in config/runtime-default flow.
- Settings/auth logic moved behind service boundaries with behavior preserved by targeted tests.
