# Task Contract: AOH-04

## Title
Decompose HubState monolith into domain services

## Objective
Replace broad `HubState` ownership with explicit services (Project, Chat, Runtime, Auth, Credentials, Artifacts, AutoConfig) and a thin orchestrator.

## Out of Scope
- route URL changes

## Allowed Edit Paths
- src/agent_hub/
- tests/

## Assumptions
- API contracts remain stable while internals are decomposed.

## Required Tests
- Unit: each service domain behavior
- Integration: API lifecycle suites
- Regression: chat start/stop/build/auth/artifact flows

## Required Validation Commands
```bash
uv run pytest tests/test_hub_and_cli.py -k "project_build or create_and_start_chat or artifacts or credentials" -q
uv run pytest tests/integration/test_hub_chat_lifecycle_api.py -q
uv run pytest tests/integration/test_agent_tools_ack_routes.py -q
```

## PR Evidence Plan
- Required artifacts:
  - service boundary map
  - call graph from route -> service -> store/runtime
  - implementation artifact: `docs/analysis/ground-up-architecture-overhaul/service_boundary_map.md`
- Visualization design:
  - none required
- Self-review gate:
  - each service has one domain and no cross-domain side effects without interface calls

## Incremental Testing Breakdown
- Baseline: map existing HubState method clusters by domain.
- Compile/Smoke: extract one service at a time behind adapter facade.
- Chunk Validation: run targeted tests after each extraction.
- Integration Validation: run affected API integration suites.
- Final Validation: run required commands.
- Diagnostics Discipline:
  - preserve consistent error-class and reason logging on service boundaries.

## Logging and Diagnostics Plan
- service-level structured logger names (`hub.project`, `hub.chat`, etc.).

## Acceptance Criteria
- [x] HubState no longer owns all domains directly.
- [x] route behavior remains stable with passing regression suites.

## Status
Status: COMPLETE

## Execution Log
```text
command: uv run pytest tests/test_hub_and_cli.py -k "project_build or create_and_start_chat or artifacts or credentials" -q
result: 31 passed, 301 deselected, 3 warnings
notes: chat/build/artifact/credential behavior stable after settings/auth service extraction

command: uv run pytest tests/integration/test_hub_chat_lifecycle_api.py -q
result: 6 passed, 12 warnings in 4.26s
notes: API lifecycle routes remain stable after codex_args route contract tightening

command: uv run pytest tests/integration/test_agent_tools_ack_routes.py -q
result: 2 passed, 4 warnings in 0.09s
notes: agent-tools ack route behavior stable

command: uv run --python 3.13 -m pytest tests/test_hub_and_cli.py -k "project_build or create_and_start_chat or artifacts or credentials" -q
result: 31 passed, 313 deselected, 2 warnings
notes: chat/build/artifact/credential behavior remains stable after strict state validation updates

command: uv run --python 3.13 -m pytest tests/integration/test_hub_chat_lifecycle_api.py -q
result: 6 passed, 12 warnings in 4.26s
notes: lifecycle API behavior remains stable

command: uv run --python 3.13 -m pytest tests/integration/test_agent_tools_ack_routes.py -q
result: 2 passed, 4 warnings in 0.09s
notes: ack route behavior remains stable
```
