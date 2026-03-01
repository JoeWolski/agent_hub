# Design Spec: Runtime UID/GID Propagation for Chat Runtime

## Design Goals
- Keep runtime identity deterministic by passing explicit UID/GID from hub into `agent_cli`.
- Preserve existing Docker-in-Docker mount and snapshot robustness behavior.
- Avoid behavior drift across snapshot prepare and chat start paths.

## Non-Goals
- No change to callback forwarding/auth behavior.
- No change to container image build layers or entrypoint user mapping logic.

## Interfaces
- Updated `HubState._prepare_agent_cli_command(...)` to include:
  - `--local-uid <self.local_uid>`
  - `--local-gid <self.local_gid>`
  - `--local-supplementary-gids <self.local_supp_gids>` (only when non-empty)

## Data Flow
1. Hub computes local identity (`self.local_uid`, `self.local_gid`, `self.local_supp_gids`) at startup.
2. Every hub-generated `agent_cli` launch command now carries explicit local identity args.
3. `agent_cli` uses those values to set `docker run --user <uid>:<gid>` and runtime setup ownership behavior.
4. Snapshot copied-in-image setup keeps project ownership aligned with final runtime user.

## Build/Test Impact
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`

## Rollback Plan
- Revert `HubState._prepare_agent_cli_command` identity argument additions.
- Revert associated command-composition tests.
