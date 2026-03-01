# Verification Plan: Architecture Overhaul Migration

## Scope
Validate that the migration preserves both required use cases while eliminating redundant/fallback-heavy behavior and converging on one runtime config source.

## Test Strategy Overview
- Baseline first, then incremental migration gates.
- Every phase has:
  - unit checks (fast, <1s for new tests)
  - subsystem checks
  - integration checks (real Docker daemon)
  - regression checks for identity/path ownership and DIND behavior

## User Story Validation Matrix

### Story A: Zero-argument launch works
Checks:
- `uv run agent_hub` and `uv run agent_cli --project <repo>` with minimal/no extra flags.
- runtime username equals host username.
- writes under mounted project are owned by host uid/gid.
- `/workspace` ownership matches runtime identity.

### Story B: Nested agent_hub inside chat (DIND)
Checks:
- nested launch can mount daemon-visible paths.
- callback/artifact endpoints are reachable from nested containers.
- full hub API integration suites pass in DIND mode.

## Incremental Validation Gates

### Gate 0: Baseline Snapshot
Commands:
```bash
uv run pytest tests/test_hub_and_cli.py -q
uv run pytest tests/integration/test_runtime_workspace_ownership.py -q
uv run python tools/testing/preflight_integration_env.py
uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight --dry-run
```
Pass criteria:
- all commands succeed
- baseline launch profiles and state payloads recorded

### Gate 1: Core Extraction Parity
Commands:
```bash
uv run pytest tests/test_hub_and_cli.py -k "prepare_agent_cli_command or launch_profile" -q
uv run pytest tests/test_hub_and_cli.py -k "host_identity or runtime_identity" -q
```
Pass criteria:
- new core abstractions produce identical launch args for representative fixtures

### Gate 2: Identity/Path Contract Enforcement
Commands:
```bash
uv run pytest tests/integration/test_runtime_workspace_ownership.py -q
uv run pytest tests/integration/test_chat_lifecycle_ready.py -q
uv run pytest tests/test_preflight_integration_env.py -q
```
Pass criteria:
- writable probes pass
- DIND tmp-host mapping present in launch profiles

### Gate 3: Service Decomposition Safety
Commands:
```bash
uv run pytest tests/test_hub_and_cli.py -k "project_build or create_and_start_chat or artifacts or credentials" -q
uv run pytest tests/test_agent_tools_ack.py -q
```
Pass criteria:
- unchanged external API behavior for project/chat/auth/artifact flows

### Gate 4: Fallback Pruning
Commands:
```bash
uv run pytest tests/test_hub_and_cli.py -k "openai_account_callback or credential_binding or state_payload" -q
uv run pytest tests/integration/test_hub_chat_lifecycle_api.py -q
```
Pass criteria:
- removed fallback paths have explicit deterministic failures
- only DIND path/network exception branches remain

### Gate 5: Full Integration and Drift Detection
Commands:
```bash
uv run python tools/testing/run_integration.py --mode direct-agent-cli --preflight
uv run python tools/testing/run_integration.py --mode hub-api-e2e --preflight
```
Pass criteria:
- both suites pass end-to-end
- no regression in startup/readiness and artifact flows

## Redundancy/Dead-Code Verification
- Add static checks for:
  - duplicate helper signatures across modules
  - unused env var constants
  - unreachable state migration branches after final schema cutover
- Validate with:
```bash
rg -n "^def " src/agent_cli src/agent_hub src/agent_core
rg -n "^[A-Z0-9_]+\s*=\s*\"[A-Z0-9_]+\"" src/agent_cli src/agent_hub src/agent_core
```

## Logging Validation
- Assert logs include required structured keys in critical operations (chat start/stop, snapshot build, callback forward, artifact publish).
- Verify log level controls suppress debug noise in default mode while preserving diagnostics at debug.

## Residual Risk
- Largest risk is behavior drift during service extraction from `HubState`.
- Mitigation: keep adapter facade + parity tests until final cutover, then remove legacy layer in one controlled PR.

