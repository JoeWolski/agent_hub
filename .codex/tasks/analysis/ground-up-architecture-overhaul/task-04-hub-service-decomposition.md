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
- [ ] HubState no longer owns all domains directly.
- [ ] route behavior remains stable with passing regression suites.

## Status
Status: TODO

## Execution Log
```text
command: pending
result: pending
notes: pending
```

## Remaining Risks
- inadvertent behavior drift during staged extraction.

