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
- [ ] runtime user and ownership semantics are deterministic.
- [ ] only approved DIND path/network branches remain.

## Status
Status: TODO

## Execution Log
```text
command: pending
result: pending
notes: pending
```

## Remaining Risks
- host daemon topology differences across environments.

