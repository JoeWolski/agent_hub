# Integration-Only RW Mount Preflight

## Status

SPEC COMPLETE

## Goal

Stop running RW mount preflight checks during normal production chat startup while preserving a deterministic way for integration coverage to opt into the same checks. New chats should no longer spend time probing writable mounts unless the caller explicitly requested preflight for test coverage.

## Non-Goals

- Do not remove the underlying RW mount validation helper.
- Do not change daemon-visible mount validation.
- Do not redesign snapshot build logic or project launch-profile wiring.

## Scope

- Gate launch-pipeline RW mount preflight behind an explicit opt-in on `agent_cli`.
- Keep the default behavior production-safe and fast: no RW preflight unless the caller opts in.
- Update direct CLI tests to cover both default-off and opt-in behavior.

## User Stories

- As a production user starting a new chat, I do not pay a per-launch RW mount probe cost on every startup.
- As a developer running integration coverage, I can still enable RW preflight explicitly when I want mount diagnostics or regression coverage.

## Acceptance Criteria

- A normal `agent_cli` launch with RW mounts must not print `Running RW mount preflight checks`.
- A normal `agent_cli` launch with RW mounts must not call the RW preflight validator.
- Project bind mount preflight is applicable iff `use_project_bind_mount` is true.
- `use_project_bind_mount = not (snapshot_tag and (prepare_snapshot_only or project_in_image))`.
- An explicit integration/test opt-in must continue to:
  - print `Running RW mount preflight checks`
  - validate every explicit `--rw-mount`
  - validate the project bind mount only when `use_project_bind_mount` is true
  - fail with the existing RW preflight error messages when validation fails
- Snapshot-only and non-snapshot launches use the same opt-in gate; do not keep preflight enabled by default for one mode.
- `agent_cli --help` must not contain the literal string `--rw-mount-preflight`.

## Class Inventory

- `agent_cli.cli.main(...)`
  - add hidden flag parameter `run_rw_mount_preflight: bool`
  - Click contract: `@click.option("--rw-mount-preflight", is_flag=True, default=False, hidden=True)`
- `agent_cli.services.LaunchPipelineInput`
  - add `run_rw_mount_preflight: bool`
  - Invariant: the CLI resolves the final boolean; no further normalization occurs downstream.
- `agent_cli.services.LaunchPipelineExecutor.execute(self) -> None`
  - Execution-order invariant: `_run_rw_preflight()` must execute after `_build_run_args()` populates `rw_mount_specs` and before snapshot image build/reuse or docker launch side effects.
- `agent_cli.services.LaunchPipelineExecutor._run_rw_preflight(self) -> None`

## Interfaces And Data

- `agent_cli.cli.main(...)`
  - Add a hidden boolean CLI flag `--rw-mount-preflight`.
  - Pass the resulting boolean into `LaunchPipelineInput.run_rw_mount_preflight`.
  - The only control surface for this behavior is the hidden CLI flag. Do not infer opt-in from snapshot mode, `prepare_snapshot_only`, `project_in_image`, environment variables, runtime config, or hub launch profiles.
- `LaunchPipelineInput`
  - Store the preflight opt-in as a plain boolean; no persisted hub schema changes.
- `LaunchPipelineExecutor._run_rw_preflight(...)`
  - Return immediately unless both conditions are true:
    - `self.data.run_rw_mount_preflight` is true
    - `self.rw_mount_specs` is non-empty
  - Read `rw_mount_specs` populated by `_collect_mount_and_env_inputs()` and `_build_run_args()`; do not recompute mount coverage locally.
  - Preserve the existing logging and validation loop when enabled.

## Error Model

- Default production launches no longer raise RW preflight errors because the preflight phase is skipped.
- Explicit opt-in launches preserve the exact existing validation failures and message format.
- If `--rw-mount-preflight` is enabled and validation fails, exit before invoking docker run, docker build, or docker commit for that launch.

## Concurrency Model

- No new concurrency behavior. This is a launch-time gate only.

## Implementation Notes

- Primary files:
  - [`src/agent_cli/cli.py`](/home/joew/projects/agent_hub/src/agent_cli/cli.py)
  - [`src/agent_cli/services.py`](/home/joew/projects/agent_hub/src/agent_cli/services.py)
  - [`tests/test_hub_and_cli.py`](/home/joew/projects/agent_hub/tests/test_hub_and_cli.py)
- Keep the switch internal by marking the Click option hidden.
- Do not thread this flag through hub launch-profile generation; production hub-launched chats should continue using the default-off behavior.
- Integration tests that need launch-pipeline preflight should opt in explicitly when invoking `agent_cli.main`.
- Add direct CLI coverage for:
  - non-snapshot default-off
  - non-snapshot opt-in
  - snapshot prepare-only default-off
  - snapshot prepare-only opt-in
  - snapshot runtime with `--project-in-image` default-off
  - snapshot runtime with `--project-in-image` opt-in validating explicit RW mounts only
  - snapshot prepare-only with `--project-in-image` opt-in validating explicit RW mounts only
  - hidden help output

## Verification Plan

- No repo-local `./make.sh` wrapper is present in this checkout. Use direct pytest commands.
- Command: `uv run python -m pytest tests/test_hub_and_cli.py -k "non_snapshot_launch_skips_rw_mount_preflight_by_default or non_snapshot_launch_validates_rw_mount_preflight_when_opted_in or snapshot_prepare_only_skips_rw_mount_preflight_by_default or snapshot_prepare_only_validates_rw_mount_preflight_when_opted_in or snapshot_prepare_only_fails_rw_mount_preflight_when_opted_in_and_owner_uid_mismatches or snapshot_runtime_project_in_image_skips_rw_mount_preflight_by_default or snapshot_runtime_project_in_image_validates_explicit_rw_mount_preflight_when_opted_in or snapshot_prepare_only_project_in_image_validates_explicit_rw_mount_preflight_when_opted_in or cli_help_hides_rw_mount_preflight_flag"`
  - Expected: all selected tests pass.

## PR Evidence Plan

- No UI evidence required because this is a CLI/backend launch behavior change.

## Ambiguity Register

- Requirement: “integration tests” means explicit test-time opt-in, not implicit detection from runtime mode or environment.
- Requirement: existing direct helper tests for `_validate_rw_mount(...)` remain unchanged because they validate the helper itself, not whether launches invoke it by default.
