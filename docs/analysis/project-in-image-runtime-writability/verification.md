# Verification Plan: Project-In-Image Runtime Writability

## Scope
Validate that snapshot-backed project-in-image chats always start with writable project directories for the runtime user, including cached-snapshot and fresh-build paths.

## Assumptions
- Docker daemon is reachable and deterministic in this environment.
- Runtime user identity for chat launches is consistent with hub-configured `local_uid/local_gid`.
- Snapshot tags are derived from stable project/snapshot schema inputs.

## Hazards
- Silent reuse of snapshots built without ownership repair.
- Ownership mismatch between snapshot build context and chat runtime user.
- Regression that reintroduces host bind-mount overlays masking image workspace ownership bugs.

## Failure Modes
- `Permission denied` for file writes inside `/workspace/<project>` in new chat.
- Snapshot build succeeds despite non-writable workspace for runtime user.
- Tests cover CLI happy path only and miss hub-orchestrated snapshot build behavior.

## Required Controls
- Control A: snapshot build command for project snapshots carries explicit in-image workspace mode.
- Control B: ownership repair executes for snapshots that copy repo into image.
- Control C: post-repair writability probe gate before `docker commit`.
- Control D: regression tests for hub + cli command path and writability outcomes.
- Control E: snapshot invalidation/versioning strategy for stale pre-fix snapshots.

## Verification Mapping
- Control A -> unit test on `HubState._prepare_agent_cli_command` / project snapshot launch profile.
- Control B -> unit test asserting `docker exec ... chown -R` appears in snapshot prepare flow.
- Control C -> unit test for failure path (probe failure aborts commit) and success path.
- Control D -> integration test: launch new chat from built snapshot and execute write command in workspace.
- Control E -> unit test for snapshot schema/version effect on expected tag.

## Residual Risk
- Environments with unusual user namespace remapping may still need additional guardrails.
- Existing cached snapshots outside schema/version governance could persist in external deployments until manually pruned.
