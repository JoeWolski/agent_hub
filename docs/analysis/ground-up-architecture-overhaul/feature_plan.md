# Feature Plan: Ground-Up Architecture Overhaul

## Objective
Redesign `agent_hub` + `agent_cli` into a clear, modular, fail-fast system with one source of truth for runtime identity/configuration and minimal branch logic, while preserving both primary and secondary Docker-in-Docker use cases.

## Problem Summary (From Current Codebase)
- Runtime/control-plane logic is concentrated in a monolith: `src/agent_hub/server.py` (~13,972 LOC, ~543 `def`s, ~68 HTTP/WebSocket routes).
- CLI orchestration is also monolithic: `src/agent_cli/cli.py` (~2,252 LOC, ~89 `def`s).
- Core helpers are duplicated between hub and CLI (`_repo_root`, `_default_config_file`, `_default_system_prompt_file`, `_docker_image_exists`, `_parse_gid_csv`, `_normalize_csv`, `_split_host_port`, option parsing helpers).
- `HubState` owns too many domains: state store, project lifecycle, chat lifecycle, runtime process supervision, auth, credential materialization, artifact publication, auto-config, and event fanout.
- Identity/config behavior is split across CLI args, env vars, defaults, and fallback code paths (host identity, temporary path mapping, callback forwarding host candidates, legacy state backfills).
- Reliability branches are broad and layered; many are compatibility/fallback behavior rather than strict contracts.

## Primary User Story (Must Not Regress)
As a host user, I launch `agent_hub`/`agent_cli` with no arguments and everything works:
- runtime user in container maps cleanly to host UID/GID
- `/workspace` ownership and mounted volume writes are indistinguishable from native host writes
- chat username matches host username
- config/auth/agent defaults resolve deterministically from one canonical runtime config

## Secondary User Story (Must Be Explicitly Supported)
As a chat running inside Docker-in-Docker, launching nested `agent_hub` for integration tests works deterministically:
- daemon-visible mount sources are used for all required bind mounts
- network callback/artifact URLs are container-reachable
- only permitted conditional branches: daemon-visible path adaptation and container-network reachability

## Non-Goals
- UI redesign
- introducing new providers or auth systems
- preserving all historical compatibility shims where they conflict with fail-fast behavior

## Design Constraints
- One source of truth for: username, uid, gid, supplementary gids, paths, credentials, MCP server injection, agent defaults, and logging policy.
- Fail fast and fail hard for invalid config/state; no silent fallback to ambiguous behavior.
- Remove unused code/tests/env vars and duplicated checks.
- Keep only narrowly justified branches for Docker-in-Docker path/network adaptation.

## Architecture Decomposition (Current)
- `agent_cli` currently combines: config loading, prompt-context assembly, provider runtime policy, Docker image build orchestration, runtime bridge startup, mount path normalization, and snapshot/bootstrap orchestration.
- `agent_hub` currently combines: FastAPI route layer, process manager, persistent state manager, auth/token handling, credential resolver, project build scheduler, runtime launch command builder, chat logs/artifacts, and callback forwarding.
- `agent_tools_mcp` is mostly cohesive, but still depends on implicit runtime env contracts and ad-hoc retry/env parsing.

## Proposed Workstreams
1. Domain extraction and module boundaries.
2. Canonical runtime config contract (single schema).
3. Runtime identity and filesystem contract unification.
4. Launch pipeline simplification and fallback elimination.
5. State schema simplification + explicit migrations.
6. Logging and error taxonomy standardization.
7. Test topology rewrite for migration safety.

## Migration Strategy (High Level)
- Strangler-fig migration with parallel adapters.
- Freeze legacy behavior behind explicit compatibility layer.
- Move one domain at a time to new modules.
- Remove legacy branch paths once replacement reaches parity and tests pass.

## PR Evidence Plan
- Required artifacts:
  - `feature_plan.md`, `design_spec.md`, `verification.md`
  - task contracts under `.codex/tasks/analysis/architecture-overhaul/`
  - `feedback_log.md`
- Visualization design:
  - Not required for this architecture-only planning cycle.
- Self-review gate:
  - confirm every proposed module has a single responsibility and explicit owner
  - confirm every fallback branch in scope is either removed or justified by approved DIND path/network exception

