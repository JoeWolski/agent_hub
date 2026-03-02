from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import click


@dataclass
class BuildService:
    base_image: str
    base_image_tag: str | None
    base_docker_path: str | None
    base_docker_context: str | None
    base_dockerfile: str | None
    project_path: Path
    cwd: Path
    agent_cli_base_image: str
    resolve_base_image: Callable[[str | None, str | None, str | None, Path, Path], tuple[str, Path, Path] | tuple[None, None, None]]
    run_command: Callable[[Sequence[str], Path | None], None]
    ensure_agent_cli_base_image_built: Callable[[], None]
    sanitize_tag_component: Callable[[str], str]
    short_hash: Callable[[str], str]
    click_echo: Callable[..., None]

    _selected_base_image: str = ""
    _selected_base_image_resolved: bool = False

    def ensure_selected_base_image(self) -> str:
        if self._selected_base_image_resolved:
            return self._selected_base_image

        self._selected_base_image = self.base_image
        if self.base_docker_path or self.base_docker_context or self.base_dockerfile:
            _, resolved_context, resolved_dockerfile = self.resolve_base_image(
                self.base_docker_path,
                self.base_docker_context,
                self.base_dockerfile,
                self.project_path,
                self.cwd,
            )
            if resolved_dockerfile is None or resolved_context is None:
                raise click.ClickException("Unable to resolve a valid base docker source")

            tag = self.base_image_tag or (
                f"agent-base-{self.sanitize_tag_component(self.project_path.name)}-"
                f"{self.sanitize_tag_component(resolved_context.name)}-"
                f"{self.short_hash(str(resolved_dockerfile))}"
            )

            self.click_echo(f"Building base image '{tag}' from {resolved_dockerfile}")
            self.run_command(
                ["docker", "build", "-f", str(resolved_dockerfile), "-t", tag, str(resolved_context)],
                None,
            )
            self._selected_base_image = tag
        elif self._selected_base_image == self.agent_cli_base_image:
            self.ensure_agent_cli_base_image_built()

        self._selected_base_image_resolved = True
        return self._selected_base_image


@dataclass
class SnapshotService:
    none_provider: str
    codex_provider: str
    claude_provider: str
    gemini_provider: str
    default_container_home: str
    snapshot_source_project_path: str
    snapshot_setup_runtime_image_for_snapshot: Callable[[str], str]
    snapshot_runtime_image_for_provider: Callable[[str, str], str]
    ensure_runtime_image_built_if_missing: Callable[..., None]
    build_runtime_image: Callable[..., None]
    build_snapshot_setup_shell_script: Callable[..., str]
    sanitize_tag_component: Callable[[str], str]
    short_hash: Callable[[str], str]
    docker_rm_force: Callable[[str], None]
    run_command: Callable[[Sequence[str], Path | None], None]
    click_echo: Callable[..., None]

    def resolve_runtime_image(
        self,
        *,
        default_runtime_image: str,
        selected_agent_provider: str,
        snapshot_tag: str,
        prepare_snapshot_only: bool,
        cached_snapshot_exists: bool,
        use_project_bind_mount: bool,
        setup_script: str | None,
        run_args: Sequence[str],
        daemon_project_path: Path,
        container_project_path: str,
        project_path: Path,
        uid: int,
        gid: int,
        ensure_selected_base_image: Callable[[], str],
    ) -> str:
        runtime_image = default_runtime_image
        if snapshot_tag:
            setup_runtime_image = self.snapshot_setup_runtime_image_for_snapshot(snapshot_tag)
            should_build_snapshot = not cached_snapshot_exists
            if should_build_snapshot:
                self.ensure_runtime_image_built_if_missing(
                    base_image=ensure_selected_base_image(),
                    target_image=setup_runtime_image,
                    agent_provider=self.none_provider,
                )
                script = (setup_script or "").strip() or ":"
                snapshot_workspace_copied_into_image = not use_project_bind_mount
                setup_bootstrap_script = self.build_snapshot_setup_shell_script(
                    script,
                    source_project_path=self.snapshot_source_project_path,
                    target_project_path=container_project_path,
                    runtime_uid=uid if snapshot_workspace_copied_into_image else None,
                    runtime_gid=gid if snapshot_workspace_copied_into_image else None,
                    enforce_project_writable_for_runtime_user=snapshot_workspace_copied_into_image,
                )
                self.click_echo(f"Building setup snapshot image '{snapshot_tag}'")
                container_name = (
                    f"agent-setup-{self.sanitize_tag_component(project_path.name)}-"
                    f"{self.short_hash(snapshot_tag + script)}"
                )
                setup_run_args = list(run_args)
                if snapshot_workspace_copied_into_image:
                    user_arg_index = setup_run_args.index("--user")
                    setup_run_args[user_arg_index + 1] = "0:0"
                setup_run_args.extend(["--volume", f"{daemon_project_path}:{self.snapshot_source_project_path}:ro"])
                setup_cmd = [
                    "docker",
                    "run",
                    "--name",
                    container_name,
                    *setup_run_args,
                    setup_runtime_image,
                    "bash",
                    "-lc",
                    setup_bootstrap_script,
                ]
                self.docker_rm_force(container_name)
                try:
                    self.run_command(setup_cmd, None)
                    self.run_command(
                        [
                            "docker",
                            "commit",
                            "--change",
                            "USER 0",
                            "--change",
                            f"WORKDIR {self.default_container_home}",
                            "--change",
                            'ENTRYPOINT ["/usr/local/bin/docker-entrypoint.py"]',
                            "--change",
                            'CMD ["bash"]',
                            container_name,
                            snapshot_tag,
                        ],
                        None,
                    )
                finally:
                    self.docker_rm_force(container_name)
            runtime_image = snapshot_tag
            if not prepare_snapshot_only and selected_agent_provider in {
                self.codex_provider,
                self.claude_provider,
                self.gemini_provider,
            }:
                provider_snapshot_runtime_image = self.snapshot_runtime_image_for_provider(
                    snapshot_tag,
                    selected_agent_provider,
                )
                self.ensure_runtime_image_built_if_missing(
                    base_image=snapshot_tag,
                    target_image=provider_snapshot_runtime_image,
                    agent_provider=selected_agent_provider,
                )
                runtime_image = provider_snapshot_runtime_image
            return runtime_image

        if prepare_snapshot_only:
            raise click.ClickException("--prepare-snapshot-only requires --snapshot-image-tag")
        self.build_runtime_image(
            base_image=ensure_selected_base_image(),
            target_image=runtime_image,
            agent_provider=selected_agent_provider,
        )
        return runtime_image


@dataclass
class LaunchService:
    start_agent_tools_runtime_bridge: Callable[..., Any]
    prepare_daemon_visible_file_mount_source: Callable[..., Path]
    run_command: Callable[[Sequence[str], Path | None], None]
    compile_docker_run_command: Callable[[Any], list[str]]
    docker_run_plan_factory: Callable[..., Any]

    def launch(
        self,
        *,
        project_path: Path,
        host_codex_dir: Path,
        config_path: Path,
        system_prompt_path: Path,
        agent_tools_config_path: Path | None,
        parsed_env_vars: list[str],
        agent_provider: Any,
        container_home_path: str,
        runtime_config: Any,
        effective_run_mode: str,
        run_args: Sequence[str],
        mcp_config_mount_target: str,
        mcp_config_mount_mode: str,
        runtime_image: str,
        command: Sequence[str],
        allocate_tty: bool,
        tmpfs_spec: str,
    ) -> None:
        runtime_bridge = None
        runtime_run_args = list(run_args)
        try:
            runtime_bridge = self.start_agent_tools_runtime_bridge(
                project_path=project_path,
                host_codex_dir=host_codex_dir,
                config_path=config_path,
                system_prompt_path=system_prompt_path,
                agent_tools_config_path=agent_tools_config_path,
                parsed_env_vars=parsed_env_vars,
                agent_provider=agent_provider,
                container_home=container_home_path,
                runtime_config=runtime_config,
                effective_run_mode=effective_run_mode,
            )
            if runtime_bridge is not None:
                runtime_run_args = list(run_args)
                runtime_config_mount_source = self.prepare_daemon_visible_file_mount_source(
                    runtime_bridge.runtime_config_path,
                    label="agent_tools runtime config",
                )
                runtime_mount = f"{runtime_config_mount_source}:{mcp_config_mount_target}{mcp_config_mount_mode}"

                replaced_mount = False
                for index in range(len(runtime_run_args) - 1):
                    if runtime_run_args[index] != "--volume":
                        continue
                    current_mount = str(runtime_run_args[index + 1])
                    parts = current_mount.split(":")
                    if len(parts) < 2:
                        continue
                    current_target = parts[1]
                    if current_target != mcp_config_mount_target:
                        continue
                    runtime_run_args[index + 1] = runtime_mount
                    replaced_mount = True
                    break

                if not replaced_mount:
                    runtime_run_args.extend(["--volume", runtime_mount])
                for runtime_env in runtime_bridge.env_vars:
                    runtime_run_args.extend(["--env", runtime_env])

            docker_run_plan = self.docker_run_plan_factory(
                runtime_image=runtime_image,
                command=tuple(command),
                run_args=tuple(runtime_run_args),
                allocate_tty=allocate_tty,
                tmpfs_spec=tmpfs_spec,
            )
            cmd = self.compile_docker_run_command(docker_run_plan)
            self.run_command(cmd, None)
        finally:
            if runtime_bridge is not None:
                close = getattr(runtime_bridge, "close", None)
                if callable(close):
                    close()
