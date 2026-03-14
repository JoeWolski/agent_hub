# Codex Runtime Home Trust Persistence

## Status

SPEC COMPLETE

## Goal

Stop Codex chats from repeatedly asking whether the workspace is trusted, and stop Codex preference saves from failing inside containers because `config.toml` is mounted through a split `.codex` directory/file layout.

## Non-Goals

- Do not change Claude or Gemini runtime-home behavior beyond keeping their existing launch path working.
- Do not redesign agent-tools bridge token issuance or chat runtime config generation.
- Do not make project snapshot build semantics depend on Codex config persistence.

## Scope

- Preseed Codex trust for the container workspace root and the container project path.
- Give Codex a single writable runtime `CODEX_HOME` directory per launch instead of relying on `/workspace/.codex/config.toml` as a separately mounted file.
- Keep existing `.codex` shared mount available for bundled binaries and scripts.
- Add focused regressions for trust injection, Codex runtime-home overlay wiring, and cleanup.

## Acceptance Criteria

- Codex runtime config generation must mark both the workspace root (`/workspace`) and the specific container project path as `trusted`.
- Codex launch command assembly must add trust overrides for both `/workspace` and the container project path unless the user already supplied the same `--config` key explicitly.
- Codex launches that use the agent-tools runtime bridge must set `CODEX_HOME` to a per-launch writable container path and mount a matching writable host directory there.
- The Codex runtime-home overlay must contain the merged `config.toml` used for that launch.
- Closing the runtime bridge must clean up the per-launch Codex runtime-home directory and the temporary runtime config file.
- Claude and Gemini launches must continue to use their existing runtime config mount replacement path.

## Class Inventory

- `agent_hub.server`
  - `_upsert_codex_trusted_project_config(base_config_text: str, container_project_path: str) -> str`
    - Invariant: the returned TOML must preserve unrelated settings and ensure both the workspace root and target project path are trusted.
- `agent_cli.cli`
  - `_AgentToolsRuntimeBridge`
    - Must be able to carry extra mount entries and skip default runtime-config mount replacement for Codex.
    - Must clean up temporary runtime config files and any temporary Codex runtime-home directory it creates.
  - `_build_agent_tools_runtime_config(...) -> Path`
    - Continues to produce the merged launch-time config file with `agent_tools` MCP wiring.
  - `_materialize_codex_runtime_home(...) -> Path`
    - Creates a per-launch writable Codex home directory seeded from the shared host `.codex` directory and the merged launch config.
  - `_start_agent_tools_runtime_bridge(...) -> _AgentToolsRuntimeBridge | None`
    - For Codex, creates the runtime-home overlay and returns the extra mount/env wiring needed to use it.
- `agent_cli.services`
  - `LaunchService.launch(...)`
    - Must honor bridge-provided extra mounts/env vars and only replace the default runtime-config mount when the bridge requests it.
  - `LaunchPipelineBuilder._compile_agent_command(...)`
    - Must inject workspace-root and project-path trust overrides for Codex without duplicating explicit user overrides.

## Interfaces And Data

- Codex runtime-home container path: `f"{container_home}/.codex-runtime"`.
- Host runtime-home path:
  - Must be created under a daemon-visible host path.
  - Must be unique per launch.
  - Must contain at least `config.toml`, plus copied shared `.codex` contents needed for Codex auth/state continuity.
- `_AgentToolsRuntimeBridge`
  - Add `mounts: list[str]`.
  - Add `mount_runtime_config: bool`.
  - Add `runtime_codex_home_path: Path | None`.
- `LaunchService.launch(...)`
  - If `mount_runtime_config` is `False`, do not replace the default config mount with `runtime_config_path`.
  - Always append any `runtime_bridge.mounts` entries as additional `--volume` flags.
- Trust injection
  - The workspace-root trust key is `projects."/workspace".trust_level`.
  - The project-path trust key remains `projects."<container_project_path>".trust_level`.

## Error Model

- If the per-launch Codex runtime-home directory cannot be created or populated, launch fails before `docker run` with a `ClickException`.
- Cleanup failures for runtime-home deletion must not mask the original launch outcome.
- Existing agent-tools runtime bridge validation and token errors remain unchanged.

## Concurrency Model

- Each launch gets its own runtime Codex home directory, so preference writes do not contend on a shared mounted `config.toml`.
- Shared host `.codex` content is only copied into the runtime home; it is not mutated by the launch path.

## Implementation Notes

- Primary files:
  - [`src/agent_hub/server.py`](/home/joew/projects/agent_hub/src/agent_hub/server.py)
  - [`src/agent_cli/cli.py`](/home/joew/projects/agent_hub/src/agent_cli/cli.py)
  - [`src/agent_cli/services.py`](/home/joew/projects/agent_hub/src/agent_cli/services.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Add regression coverage that:
  - updates Codex runtime config generation to assert both `/workspace` and the project path are trusted
  - asserts default Codex launch adds both trust overrides
  - asserts explicit user overrides are not duplicated
  - asserts Codex runtime bridge creates a runtime-home overlay, sets `CODEX_HOME`, and cleans it up
  - keeps Claude/Gemini runtime bridge mount-replacement tests passing

## Verification Plan

- No repo-local `./make.sh` wrapper is present in this checkout. Use focused pytest commands.
- Run each new or updated regression in isolation:
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_prepare_chat_runtime_config_adds_codex_project_trust_for_container_workspace`
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_agent_cli_default_run_mounts_runtime_agent_tools_config_and_env`
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_agent_cli_default_run_does_not_duplicate_explicit_codex_project_trust_override`
  - `/usr/bin/time -f '%E' uv run python -m pytest tests/test_hub_and_cli.py -k test_start_agent_tools_runtime_bridge_creates_and_cleans_up_codex_runtime_home`
- Then run the focused slice:
  - `uv run python -m pytest tests/test_hub_and_cli.py -k "prepare_chat_runtime_config_adds_codex_project_trust_for_container_workspace or agent_cli_default_run_mounts_runtime_agent_tools_config_and_env or agent_cli_default_run_does_not_duplicate_explicit_codex_project_trust_override or start_agent_tools_runtime_bridge_creates_and_cleans_up_codex_runtime_home or agent_cli_claude_runtime_bridge_replaces_default_claude_json_mount or agent_cli_gemini_runtime_bridge_replaces_default_gemini_settings_mount"`

## PR Evidence Plan

- No UI evidence required because this is runtime/container behavior only.

## Ambiguity Register

- “Trust all of workspace” means Codex should trust `/workspace` in addition to the specific project path, so nested project-local `.codex/config.toml` files are no longer rejected for lack of trust.
