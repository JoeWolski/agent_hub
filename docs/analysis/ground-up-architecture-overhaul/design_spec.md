# Design Spec: Ground-Up Architecture Overhaul

## 1. Target Architecture

### 1.1 Packages
- `src/agent_core/`
  - `config/`: typed schema, loader, validation, migration
  - `identity/`: host/runtime identity resolution and invariants
  - `paths/`: daemon-visible path adapter + mount validation
  - `launch/`: provider-neutral launch spec model + compiler to CLI args/docker args
  - `errors/`: typed errors with failure class + user-safe messages
  - `logging/`: structured logging config and per-domain loggers
- `src/agent_cli/`
  - thin command adapter only
  - delegates all runtime planning/build logic to `agent_core`
- `src/agent_hub/`
  - `api/`: FastAPI routers only
  - `services/`: project, chat, auth, credentials, artifacts, snapshots
  - `runtime/`: process supervisor and terminal stream manager
  - `store/`: state persistence and migration
  - `integrations/`: OpenAI/GitHub/GitLab and docker command execution

### 1.2 Central Contract Objects
- `RuntimeIdentity`: `username`, `uid`, `gid`, `supplementary_gids`, `umask`.
- `RuntimePaths`: `workspace_root`, `tmp_root`, `data_dir`, `config_file`, `system_prompt_file`, daemon-visible mapping.
- `AgentRuntimeConfig`: provider defaults, MCP server policy, credential resolution policy, auth endpoints, logging levels.
- `LaunchSpec`: single provider-neutral representation used by both CLI and Hub before compilation to command args.

## 2. Single Source Of Truth (SSOT)

### 2.1 Canonical Config File
- Introduce one canonical file (TOML) for all runtime configuration and defaults.
- All env vars become either:
  - boot overrides explicitly mapped into config once at startup, or
  - removed.
- All CLI flags become thin overrides to this same schema.

### 2.2 Required Schema Sections
- `[identity]`: username policy, uid/gid strategy, supplementary gid behavior.
- `[paths]`: workspace/data/tmp roots and DIND mapping policy.
- `[providers]`: codex/claude/gemini defaults.
- `[mcp]`: required servers, injection strategy, environment contract.
- `[auth]`: openai/github/gitlab settings.
- `[logging]`: level, format (json/text), redaction policy, verbosity controls per domain.
- `[runtime]`: fail-fast toggles (strict mode always enabled in production).

## 3. Runtime Identity and Ownership Contract

### 3.1 Invariants
- Runtime identity is resolved once at startup and immutable for process lifetime.
- Container process user must equal resolved `uid:gid` except controlled bootstrap phases.
- Mounted project and `/workspace` writability probe is mandatory; failure is terminal.
- Username used in runtime is `RuntimeIdentity.username`; no provider-specific username logic.

### 3.2 Allowed Branch Exceptions
Only these branches remain:
- Daemon-visible mount source rewrite for Docker-in-Docker.
- Container-reachable network host selection for callback/artifact routes.

All other fallback branches are converted into deterministic validations with explicit errors.

## 4. Service Boundaries and Responsibility Map

### 4.1 Hub Services
- `ProjectService`: project lifecycle + snapshot metadata.
- `ChatService`: chat state machine only.
- `RuntimeService`: process spawn/attach/stop and terminal IO.
- `CredentialService`: credential catalog, binding, and materialization.
- `AuthService`: OpenAI/GitHub/GitLab auth lifecycle.
- `ArtifactService`: publish/submit/download/preview.
- `AutoConfigService`: repository analysis and recommendation normalization.

`HubState` is replaced by composable services and a thin orchestrator.

### 4.2 CLI Services
- `BuildService`: image resolution/build.
- `SnapshotService`: setup bootstrap and writable verification.
- `LaunchService`: compile and execute `LaunchSpec`.

## 5. Fail-Fast Policy
- Replace soft fallback patterns (`if missing then try fallback`) with startup validation.
- Use typed exceptions:
  - `ConfigError`
  - `IdentityError`
  - `MountVisibilityError`
  - `NetworkReachabilityError`
  - `CredentialResolutionError`
- Every exception class maps to one deterministic user-facing error code.

## 6. Logging Overhaul
- Structured logs with required keys: `request_id`, `project_id`, `chat_id`, `component`, `operation`, `result`, `duration_ms`, `error_class`.
- Log-level controls per domain (`auth`, `runtime`, `docker`, `artifacts`, `auto_config`).
- Redaction at sink boundary for tokens/keys/secrets.
- No ad-hoc print/warn branches in deep core paths.

## 7. Redundancy and Fallback Removal Matrix

### 7.1 Remove/Consolidate Duplicates
- Consolidate duplicated helpers in `agent_core`:
  - option parsing helpers
  - path/default resolution
  - gid/csv parsing
  - docker image existence probe
  - repo root/config/system prompt discovery

### 7.2 Replace Compatibility Backfills
- Legacy state fields (for example chat `codex_args` backfill) move to explicit one-time state migration.
- Once migrated, runtime paths stop handling legacy keys.

### 7.3 Callback Forwarding
- Replace broad host candidate fallback loops with deterministic resolver policy:
  1. configured reachable host
  2. validated DIND bridge host
  3. fail with actionable diagnostics

## 8. Migration Plan (Incremental)

### Phase 0: Baseline and Freeze
- Capture baseline behavior and integration evidence.
- Freeze new feature work in touched modules.

### Phase 1: Core Extraction
- Introduce `agent_core` schema, identity, path, and launch primitives.
- Add adapters in CLI/Hub without behavior change.

### Phase 2: Command Planning Unification
- Make Hub and CLI both produce/consume `LaunchSpec`.
- Ensure parity with existing launch profiles.

### Phase 3: State and Service Decomposition
- Split `HubState` responsibilities into services.
- Keep API surface stable with adapter facade.

### Phase 4: Fallback Pruning
- Remove non-DIND fallback branches.
- Enforce strict config and identity validation at startup.

### Phase 5: Cleanup and Dead Code Removal
- Remove unused env vars, flags, and tests.
- Remove duplicate validations and unreachable branches.

## 9. Risk Controls
- Migration guardrails: side-by-side validation mode where legacy and new planners can be diffed.
- Hard stop on divergence for identity/mount planning.
- Feature flags only during migration; removed before final state.

## 10. Clarifications Needed Before Implementation
- Confirm canonical config filename/path for production installs.
- Confirm whether any legacy state compatibility period is required after migration release.
- Confirm acceptable strictness for startup failure when optional provider binaries are missing.

