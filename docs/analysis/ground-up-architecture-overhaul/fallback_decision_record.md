# Fallback Decision Record (AOH-05)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Removed In This Cycle
- Removed legacy top-level provider-default backfill into `providers.defaults`.
- Removed CLI shared-prompt context JSON/TOML fallback parser path in favor of canonical runtime-config parse.
- Removed implicit fallback for explicitly provided missing `--config-file` and `--system-prompt-file` paths (now fail-fast).
- Removed unsupported `--agent-command` provider fallback (hard-fail).
- Removed provider lookup fallback to Codex provider (hard-fail).
- Removed runtime run-mode silent fallback by enforcing configured/override mode requirements with explicit failures.
- Removed chat/state invalid `agent_type` normalization fallback (now strict fail-fast with deterministic 400 errors).
- Removed snapshot launch-profile runtime-image exception fallback branch.

## Kept In This Cycle
- DIND path rewrite and network reachability branches (approved exceptions).
- Explicit CLI/env startup overrides where intentionally supported by contract.
