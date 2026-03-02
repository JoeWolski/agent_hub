# Task Contract: AOH-03

## Title
Unify runtime identity, mount ownership, and DIND path/network branching

## Objective
Codify runtime identity and mount invariants, keeping only the approved branch exceptions for daemon-visible path rewriting and container-reachable network routing.

## Out of Scope
- adding non-Docker execution modes

## Allowed Edit Paths
- src/agent_core/identity/
- src/agent_core/paths/
- src/agent_cli/
- src/agent_hub/
- tests/integration/
- tests/

## Assumptions
- `/workspace` writable ownership must match resolved runtime identity.
- DIND mount source adaptation remains mandatory in nested daemon mode.

## Required Tests
- Unit: identity resolver and mount-policy logic
- Integration: runtime workspace ownership and chat lifecycle readiness
- Regression: nested hub launches can mount `/workspace/tmp` correctly

## Required Validation Commands
```bash
uv run pytest tests/integration/test_runtime_workspace_ownership.py -q
uv run pytest tests/integration/test_chat_lifecycle_ready.py -q
uv run pytest tests/test_preflight_integration_env.py -q
```

## PR Evidence Plan
- Required artifacts:
  - identity invariant checklist
  - mount rewrite decision log
  - implementation artifacts:
    - `docs/analysis/ground-up-architecture-overhaul/identity_invariant_checklist.md`
    - `docs/analysis/ground-up-architecture-overhaul/mount_decision_log.md`
- Visualization design:
  - none required
- Self-review gate:
  - no remaining non-DIND fallback identity branches

## Incremental Testing Breakdown
- Baseline: capture identity values and mount decisions from launch profile.
- Compile/Smoke: run ownership probe in smallest setup path.
- Chunk Validation: run readiness and preflight tests per change chunk.
- Integration Validation: run ownership + lifecycle suites.
- Final Validation: run required commands.
- Diagnostics Discipline:
  - include uid/gid, mount source/target, and resolver path in failures.

## Logging and Diagnostics Plan
- structured logs for identity resolution and mount rewrite decisions.

## Acceptance Criteria
- [x] runtime user and ownership semantics are deterministic.
- [x] only approved DIND path/network branches remain.

## Status
Status: COMPLETE

## Execution Log
```text
command: uv run pytest tests/integration/test_chat_lifecycle_ready.py -q
result: 3 passed in 0.02s
notes: chat readiness remains stable with config-first identity/default resolution

command: uv run pytest tests/test_preflight_integration_env.py -q
result: 2 passed in 0.02s
notes: preflight checks stable

command: uv run pytest tests/integration/test_runtime_workspace_ownership.py -q
result: failed in environment (PermissionError creating /workspace/tmp/...)
notes: environment-level filesystem permissions blocked ownership integration verification

command: uv run --python 3.13 -m pytest tests/integration/test_runtime_workspace_ownership.py -q
result: failed in environment (PermissionError creating /workspace/tmp/...)
notes: rerun after permission fix request still fails in current runtime context; `/workspace/tmp` remains non-writable

command: uv run --python 3.13 -m pytest tests/integration/test_runtime_workspace_ownership.py -q
result: 1 passed in 2.72s
notes: workspace ownership integration now passes after runtime `/workspace/tmp` resolution

command: uv run --python 3.13 -m pytest tests/integration/test_runtime_workspace_ownership.py -q
result: 1 passed in 3.56s
notes: ownership integration remains stable after strict fallback pruning

command: uv run --python 3.13 -m pytest tests/integration/test_chat_lifecycle_ready.py -q
result: 3 passed in 0.02s
notes: readiness behavior stable with strict runtime mode/agent type handling

command: uv run --python 3.13 -m pytest tests/test_preflight_integration_env.py -q
result: 2 passed in 0.01s
notes: preflight behavior stable in validated environment
```
