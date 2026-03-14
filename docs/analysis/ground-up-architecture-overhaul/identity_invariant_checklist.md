# Identity Invariant Checklist (AOH-03)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Invariants
- [x] Runtime identity resolves once during `HubState` initialization.
- [x] Config identity fields (`identity.uid`, `identity.gid`) are accepted as config-first inputs.
- [x] Runtime username can resolve from config (`identity.username`) before env/userdb fallback.
- [x] Ownership/writability invariant validated in this environment via `tests/integration/test_runtime_workspace_ownership.py`.

## Evidence
- PASS: `uv run --python 3.13 -m pytest tests/integration/test_chat_lifecycle_ready.py -q`
- PASS: `uv run --python 3.13 -m pytest tests/test_preflight_integration_env.py -q`
- PASS: `uv run --python 3.13 -m pytest tests/integration/test_runtime_workspace_ownership.py -q`
