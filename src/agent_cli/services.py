from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import click
from agent_core import launch as core_launch


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

    @staticmethod
    def _require_user_flag_for_snapshot_setup(run_args: Sequence[str]) -> int:
        setup_run_args = list(run_args)
        if "--user" not in setup_run_args:
            raise click.ClickException(
                "Snapshot setup requires docker run arguments to include --user for root bootstrap rewrite."
            )
        user_arg_index = setup_run_args.index("--user")
        if user_arg_index + 1 >= len(setup_run_args):
            raise click.ClickException(
                "Snapshot setup requires a --user value for root bootstrap rewrite."
            )
        return user_arg_index

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
                    user_arg_index = self._require_user_flag_for_snapshot_setup(setup_run_args)
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


@dataclass(frozen=True)
class LaunchPipelineInput:
    ro_mounts: tuple[str, ...]
    rw_mounts: tuple[str, ...]
    env_vars: tuple[str, ...]
    container_args: tuple[str, ...]
    selected_agent_provider: str
    selected_agent_command: str
    no_alt_screen: bool
    resume: bool
    snapshot_tag: str
    prepare_snapshot_only: bool
    project_in_image: bool
    setup_script: str | None
    cached_snapshot_exists: bool
    project_path: Path
    daemon_project_path: Path
    container_project_path: str
    container_project_root: Any
    config_path: Path
    system_prompt_path: Path
    host_codex_dir: Path
    host_claude_dir: Path
    host_claude_json_file: Path
    host_claude_config_dir: Path
    host_gemini_dir: Path
    host_gemini_settings_file: Path
    container_home_path: str
    runtime_identity: Any
    supplemental_group_ids: list[int]
    bootstrap_as_root: bool
    api_key: str | None
    runtime_config: Any
    effective_run_mode: str
    allocate_tty: bool
    shared_prompt_context: str


@dataclass(frozen=True)
class LaunchPipelineDeps:
    click_echo: Callable[..., None]
    parse_mount: Callable[[str, str], tuple[str, str]]
    parse_env_var: Callable[[str, str], str]
    reject_mount_inside_project_path: Callable[..., None]
    validate_daemon_visible_mount_source: Callable[..., None]
    daemon_visible_mount_source: Callable[[Path], Path]
    validate_rw_mount: Callable[[Path, str, int, int], None]
    prepare_daemon_visible_file_mount_source: Callable[..., Path]
    has_codex_config_override: Callable[..., bool]
    resolved_runtime_term: Callable[[], str]
    resolved_runtime_colorterm: Callable[[], str]
    platform_startswith_linux: Callable[[], bool]
    default_runtime_image_for_provider: Callable[[str], str]
    snapshot_setup_runtime_image_for_snapshot: Callable[[str], str]
    snapshot_runtime_image_for_provider: Callable[[str, str], str]
    ensure_runtime_image_built_if_missing: Callable[..., None]
    build_runtime_image: Callable[..., None]
    build_snapshot_setup_shell_script: Callable[..., str]
    sanitize_tag_component: Callable[[str], str]
    short_hash: Callable[[str], str]
    docker_rm_force: Callable[[str], None]
    run_command: Callable[[Sequence[str], Path | None], None]
    start_agent_tools_runtime_bridge: Callable[..., Any]
    compile_docker_run_command: Callable[[Any], list[str]]
    docker_run_plan_factory: Callable[..., Any]
    snapshot_source_project_path: str
    default_container_home: str
    agent_provider_none: str
    agent_provider_codex: str
    agent_provider_claude: str
    agent_provider_gemini: str
    docker_socket_path: str
    tmp_dir_tmpfs_spec: str


@dataclass
class LaunchPipelineExecutor:
    data: LaunchPipelineInput
    deps: LaunchPipelineDeps
    build_service: BuildService
    agent_provider: Any

    ro_mount_flags: list[str] = field(default_factory=list)
    rw_mount_flags: list[str] = field(default_factory=list)
    rw_mount_specs: list[tuple[Path, str]] = field(default_factory=list)
    parsed_env_vars: list[str] = field(default_factory=list)

    def _validated_mapped_mount_source(self, host_path: Path, *, label: str) -> Path:
        mapped_source = self.deps.daemon_visible_mount_source(host_path)
        self.deps.validate_daemon_visible_mount_source(mapped_source, label=f"{label} (mapped)")
        return mapped_source

    def execute(self) -> None:
        self._collect_mount_and_env_inputs()
        command = self._compile_agent_command()
        run_args, mcp_config_mount_target, mcp_config_mount_mode, use_project_bind_mount = self._build_run_args()
        self._run_rw_preflight()
        runtime_image = self._resolve_runtime_image(run_args, use_project_bind_mount)
        if self.data.prepare_snapshot_only:
            return
        self._launch_runtime(
            run_args=run_args,
            mcp_config_mount_target=mcp_config_mount_target,
            mcp_config_mount_mode=mcp_config_mount_mode,
            runtime_image=runtime_image,
            command=command,
        )

    def _collect_mount_and_env_inputs(self) -> None:
        for mount in self.data.ro_mounts:
            self.deps.reject_mount_inside_project_path(
                spec=mount,
                label="--ro-mount",
                container_project_path=self.data.container_project_root,
            )
            host, container = self.deps.parse_mount(mount, "--ro-mount")
            host_path = Path(host)
            self.deps.validate_daemon_visible_mount_source(host_path, label="--ro-mount")
            mapped_host_path = self._validated_mapped_mount_source(host_path, label="--ro-mount")
            self.ro_mount_flags.append(f"{mapped_host_path}:{container}:ro")

        for mount in self.data.rw_mounts:
            self.deps.reject_mount_inside_project_path(
                spec=mount,
                label="--rw-mount",
                container_project_path=self.data.container_project_root,
            )
            host, container = self.deps.parse_mount(mount, "--rw-mount")
            host_path = Path(host)
            self.deps.validate_daemon_visible_mount_source(host_path, label="--rw-mount")
            mapped_host_path = self._validated_mapped_mount_source(host_path, label="--rw-mount")
            self.rw_mount_flags.append(f"{mapped_host_path}:{container}")
            self.rw_mount_specs.append((host_path, container))

        for entry in self.data.env_vars:
            self.parsed_env_vars.append(self.deps.parse_env_var(entry, "--env-var"))

    def _compile_agent_command(self) -> list[str]:
        explicit_container_args = [str(arg) for arg in self.data.container_args]
        runtime_flags = self.agent_provider.default_runtime_flags(
            explicit_args=explicit_container_args,
            shared_prompt_context=self.data.shared_prompt_context,
            no_alt_screen=self.data.no_alt_screen,
            runtime_config=self.data.runtime_config,
        )
        codex_project_trust_key = f"projects.{json.dumps(self.data.container_project_path)}.trust_level"
        if (
            self.data.selected_agent_provider == self.deps.agent_provider_codex
            and not self.deps.has_codex_config_override(explicit_container_args, key=codex_project_trust_key)
        ):
            runtime_flags.extend(["--config", f'{codex_project_trust_key}="trusted"'])

        resume_shell_command = ""
        if self.data.resume and not explicit_container_args:
            resume_shell_command = self.agent_provider.resume_shell_command(
                no_alt_screen=self.data.no_alt_screen,
                runtime_flags=runtime_flags,
            )
        command_plan = core_launch.AgentProcessLaunchPlan(
            agent_command=self.data.selected_agent_command,
            runtime_flags=tuple(runtime_flags),
            explicit_container_args=tuple(explicit_container_args),
            resume=self.data.resume,
            resume_shell_command=resume_shell_command,
        )
        return core_launch.compile_agent_process_command(command_plan)

    def _build_run_args(self) -> tuple[list[str], str, str, bool]:
        config_mount_target = f"{self.data.container_home_path}/.codex/config.toml"
        mcp_config_mount_target = self.agent_provider.get_mcp_config_mount_target(self.data.container_home_path)
        mcp_config_mount_mode = ""
        mounted_config_path = self.deps.prepare_daemon_visible_file_mount_source(self.data.config_path, label="--config-file")
        mounted_claude_json_path = self.deps.prepare_daemon_visible_file_mount_source(
            self.data.host_claude_json_file,
            label="Claude settings file",
        )
        mounted_gemini_settings_path = self.deps.prepare_daemon_visible_file_mount_source(
            self.data.host_gemini_settings_file,
            label="Gemini settings file",
        )
        mcp_mount_source = (
            mounted_gemini_settings_path if self.data.selected_agent_provider == self.deps.agent_provider_gemini else None
        )
        mcp_config_mount_entry = (
            f"{mcp_mount_source}:{mcp_config_mount_target}{mcp_config_mount_mode}" if mcp_mount_source is not None else None
        )
        config_mount_entry = f"{mounted_config_path}:{config_mount_target}"
        daemon_host_codex_dir = self._validated_mapped_mount_source(
            self.data.host_codex_dir,
            label="--agent-home-path/.codex",
        )
        daemon_host_claude_dir = self._validated_mapped_mount_source(
            self.data.host_claude_dir,
            label="--agent-home-path/.claude",
        )
        daemon_host_claude_config_dir = self._validated_mapped_mount_source(
            self.data.host_claude_config_dir,
            label="--agent-home-path/.config/claude",
        )
        daemon_host_gemini_dir = self._validated_mapped_mount_source(
            self.data.host_gemini_dir,
            label="--agent-home-path/.gemini",
        )
        project_mount_entry = f"{self.data.daemon_project_path}:{self.data.container_project_path}"
        use_project_bind_mount = not (
            bool(self.data.snapshot_tag) and (self.data.prepare_snapshot_only or self.data.project_in_image)
        )
        if use_project_bind_mount:
            self.rw_mount_specs.append((self.data.project_path, self.data.container_project_path))
        run_args = [
            "--init",
            "--user",
            ("0:0" if self.data.bootstrap_as_root else f"{self.data.runtime_identity.uid}:{self.data.runtime_identity.gid}"),
            "--gpus",
            "all",
            "--workdir",
            self.data.container_project_path,
            "--volume",
            f"{self.deps.docker_socket_path}:{self.deps.docker_socket_path}",
            "--volume",
            f"{daemon_host_codex_dir}:{self.data.container_home_path}/.codex",
            "--volume",
            f"{daemon_host_claude_dir}:{self.data.container_home_path}/.claude",
            "--volume",
            f"{mounted_claude_json_path}:{self.data.container_home_path}/.claude.json",
            "--volume",
            f"{daemon_host_claude_config_dir}:{self.data.container_home_path}/.config/claude",
            "--volume",
            f"{daemon_host_gemini_dir}:{self.data.container_home_path}/.gemini",
            "--volume",
            config_mount_entry,
            *(["--volume", mcp_config_mount_entry] if mcp_config_mount_entry is not None else []),
            "--env",
            f"LOCAL_UMASK={self.data.runtime_identity.umask}",
            "--env",
            f"LOCAL_USER={self.data.runtime_identity.username}",
            "--env",
            f"HOME={self.data.container_home_path}",
            "--env",
            "NPM_CONFIG_CACHE=/tmp/.npm",
            "--env",
            f"CONTAINER_HOME={self.data.container_home_path}",
            "--env",
            f"PATH={self.data.container_home_path}/.codex/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--env",
            f"TERM={self.deps.resolved_runtime_term()}",
            "--env",
            f"COLORTERM={self.deps.resolved_runtime_colorterm()}",
            "--env",
            "NVIDIA_VISIBLE_DEVICES=all",
            "--env",
            "NVIDIA_DRIVER_CAPABILITIES=all",
            "--env",
            f"CONTAINER_PROJECT_PATH={self.data.container_project_path}",
            "--env",
            f"UV_PROJECT_ENVIRONMENT={self.data.container_project_path}/.venv",
        ]
        if self.data.bootstrap_as_root:
            run_args.extend(["--env", f"LOCAL_UID={self.data.runtime_identity.uid}"])
            run_args.extend(["--env", f"LOCAL_GID={self.data.runtime_identity.gid}"])
            if self.data.runtime_identity.supplementary_gids:
                run_args.extend(["--env", f"LOCAL_SUPPLEMENTARY_GIDS={self.data.runtime_identity.supplementary_gids}"])
        if use_project_bind_mount:
            run_args.extend(["--volume", project_mount_entry])
        run_args.extend(["--group-add", "agent"])
        for supplemental_gid in self.data.supplemental_group_ids:
            run_args.extend(["--group-add", str(supplemental_gid)])
        if self.deps.platform_startswith_linux():
            run_args.extend(["--add-host", "host.docker.internal:host-gateway"])
        if self.data.api_key:
            run_args.extend(["--env", f"OPENAI_API_KEY={self.data.api_key}"])
        for env_entry in self.parsed_env_vars:
            run_args.extend(["--env", env_entry])
        for mount in self.ro_mount_flags + self.rw_mount_flags:
            run_args.extend(["--volume", mount])
        return run_args, mcp_config_mount_target, mcp_config_mount_mode, use_project_bind_mount

    def _run_rw_preflight(self) -> None:
        if self.rw_mount_specs:
            self.deps.click_echo("Running RW mount preflight checks", err=True)
            for host_path, container_path in self.rw_mount_specs:
                self.deps.validate_rw_mount(
                    host_path,
                    container_path,
                    runtime_uid=self.data.runtime_identity.uid,
                    runtime_gid=self.data.runtime_identity.gid,
                )

    def _resolve_runtime_image(self, run_args: list[str], use_project_bind_mount: bool) -> str:
        snapshot_service = SnapshotService(
            none_provider=self.deps.agent_provider_none,
            codex_provider=self.deps.agent_provider_codex,
            claude_provider=self.deps.agent_provider_claude,
            gemini_provider=self.deps.agent_provider_gemini,
            default_container_home=self.deps.default_container_home,
            snapshot_source_project_path=self.deps.snapshot_source_project_path,
            snapshot_setup_runtime_image_for_snapshot=self.deps.snapshot_setup_runtime_image_for_snapshot,
            snapshot_runtime_image_for_provider=self.deps.snapshot_runtime_image_for_provider,
            ensure_runtime_image_built_if_missing=self.deps.ensure_runtime_image_built_if_missing,
            build_runtime_image=self.deps.build_runtime_image,
            build_snapshot_setup_shell_script=self.deps.build_snapshot_setup_shell_script,
            sanitize_tag_component=self.deps.sanitize_tag_component,
            short_hash=self.deps.short_hash,
            docker_rm_force=self.deps.docker_rm_force,
            run_command=self.deps.run_command,
            click_echo=self.deps.click_echo,
        )
        return snapshot_service.resolve_runtime_image(
            default_runtime_image=self.deps.default_runtime_image_for_provider(self.data.selected_agent_provider),
            selected_agent_provider=self.data.selected_agent_provider,
            snapshot_tag=self.data.snapshot_tag,
            prepare_snapshot_only=self.data.prepare_snapshot_only,
            cached_snapshot_exists=self.data.cached_snapshot_exists,
            use_project_bind_mount=use_project_bind_mount,
            setup_script=self.data.setup_script,
            run_args=run_args,
            daemon_project_path=self.data.daemon_project_path,
            container_project_path=self.data.container_project_path,
            project_path=self.data.project_path,
            uid=self.data.runtime_identity.uid,
            gid=self.data.runtime_identity.gid,
            ensure_selected_base_image=self.build_service.ensure_selected_base_image,
        )

    def _launch_runtime(
        self,
        *,
        run_args: list[str],
        mcp_config_mount_target: str,
        mcp_config_mount_mode: str,
        runtime_image: str,
        command: list[str],
    ) -> None:
        launch_service = LaunchService(
            start_agent_tools_runtime_bridge=self.deps.start_agent_tools_runtime_bridge,
            prepare_daemon_visible_file_mount_source=self.deps.prepare_daemon_visible_file_mount_source,
            run_command=self.deps.run_command,
            compile_docker_run_command=self.deps.compile_docker_run_command,
            docker_run_plan_factory=self.deps.docker_run_plan_factory,
        )
        launch_service.launch(
            project_path=self.data.project_path,
            host_codex_dir=self.data.host_codex_dir,
            config_path=self.data.config_path,
            system_prompt_path=self.data.system_prompt_path,
            agent_tools_config_path=(
                self.data.host_claude_json_file
                if self.data.selected_agent_provider == self.deps.agent_provider_claude
                else self.data.host_gemini_settings_file
                if self.data.selected_agent_provider == self.deps.agent_provider_gemini
                else None
            ),
            parsed_env_vars=self.parsed_env_vars,
            agent_provider=self.agent_provider,
            container_home_path=self.data.container_home_path,
            runtime_config=self.data.runtime_config,
            effective_run_mode=self.data.effective_run_mode,
            run_args=run_args,
            mcp_config_mount_target=mcp_config_mount_target,
            mcp_config_mount_mode=mcp_config_mount_mode,
            runtime_image=runtime_image,
            command=command,
            allocate_tty=self.data.allocate_tty,
            tmpfs_spec=self.deps.tmp_dir_tmpfs_spec,
        )


def execute_launch_pipeline(
    *,
    data: LaunchPipelineInput,
    deps: LaunchPipelineDeps,
    build_service: BuildService,
    agent_provider: Any,
) -> None:
    LaunchPipelineExecutor(
        data=data,
        deps=deps,
        build_service=build_service,
        agent_provider=agent_provider,
    ).execute()
