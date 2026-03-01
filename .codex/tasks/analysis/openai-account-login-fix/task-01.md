# Task 01: OpenAI Account Callback 502 Root Cause and Fix

## Status
REVISED_COMPLETE

## Scope
- Implement robust callback forwarding fallback for Docker-in-Docker bridge routing.
- Add durable redacted diagnostics across callback resolution and forwarding.
- Prioritize direct CLI user reliability by making container loopback forwarding primary.
- Add targeted tests for success, failure, edge derivation, and logging.

## Allowed Edit Paths
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`
- `docs/analysis/openai-account-login-fix/**`

## Incremental Validation Log
1. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback_uses_resolved_default_host_for_default_startup"` -> PASS
2. Baseline deterministic repro script (pre-fix behavior) -> PASS (observed HTTP 502 as expected)
3. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback"` -> FAIL initially (log redaction gap), then PASS after fix
4. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "openai_account_callback_route"` -> PASS
5. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "parse_callback_forward_host_port"` -> PASS
6. Post-fix deterministic repro script with bridge fallback patch -> PASS (observed HTTP 200)
7. `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback or openai_account_callback_route or parse_callback_forward_host_port"` -> PASS
8. Strategy revision validation: `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback"` -> PASS
9. Strategy revision validation: `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "openai_account_callback_route or parse_callback_forward_host_port"` -> PASS

## Remaining Risks
- Unexpected network topologies beyond current bridge/default-route discovery may still require additional host candidates.
- Environments that disallow `docker exec` rely on network fallback path.
