from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class LaunchSpec:
    repo_root: Path
    workspace: Path
    container_project_name: str
    agent_home_path: Path
    runtime_config_file: Path
    system_prompt_file: Path
    agent_command: str
    run_mode: str
    local_uid: int
    local_gid: int
    local_user: str
    local_supplementary_gids: str = ""
    allocate_tty: bool = True
    resume: bool = False
    snapshot_tag: str = ""
    ro_mounts: tuple[str, ...] = ()
    rw_mounts: tuple[str, ...] = ()
    env_vars: tuple[str, ...] = ()
    extra_args: tuple[str, ...] = ()
    openai_credentials_args: tuple[str, ...] = ()
    base_args: tuple[str, ...] = ()
    setup_script: str = ""
    prepare_snapshot_only: bool = False
    project_in_image: bool = False
    bootstrap_as_root: bool = True
    no_alt_screen: bool = True


@dataclass(frozen=True)
class AgentProcessLaunchPlan:
    agent_command: str
    runtime_flags: tuple[str, ...]
    explicit_container_args: tuple[str, ...] = ()
    resume: bool = False
    resume_shell_command: str = ""


@dataclass(frozen=True)
class ParsedLaunchCommand:
    ro_mounts: tuple[str, ...]
    rw_mounts: tuple[str, ...]
    env_vars: tuple[str, ...]
    container_args: tuple[str, ...]


@dataclass(frozen=True)
class DockerRunInvocationPlan:
    runtime_image: str
    command: tuple[str, ...]
    run_args: tuple[str, ...]
    remove_container: bool = True
    interactive: bool = True
    allocate_tty: bool = True
    tmpfs_spec: str = "/tmp:mode=1777,exec"


def compile_agent_cli_command(spec: LaunchSpec) -> list[str]:
    cmd = [
        "uv",
        "run",
        "--project",
        str(spec.repo_root),
        "agent_cli",
        "--agent-command",
        str(spec.agent_command),
        "--run-mode",
        str(spec.run_mode),
        "--project",
        str(spec.workspace),
        "--container-project-name",
        str(spec.container_project_name),
        "--agent-home-path",
        str(spec.agent_home_path),
        "--config-file",
        str(spec.runtime_config_file),
        "--system-prompt-file",
        str(spec.system_prompt_file),
        "--local-uid",
        str(spec.local_uid),
        "--local-gid",
        str(spec.local_gid),
        "--local-user",
        str(spec.local_user),
    ]

    if spec.bootstrap_as_root:
        cmd.append("--bootstrap-as-root")
    if spec.no_alt_screen:
        cmd.append("--no-alt-screen")

    if spec.local_supplementary_gids:
        cmd.extend(["--local-supplementary-gids", str(spec.local_supplementary_gids)])
    if not spec.allocate_tty:
        cmd.append("--no-tty")
    if spec.resume:
        cmd.append("--resume")

    cmd.extend(str(arg) for arg in spec.openai_credentials_args)

    if spec.snapshot_tag:
        cmd.extend(str(arg) for arg in spec.base_args)
        cmd.extend(["--snapshot-image-tag", str(spec.snapshot_tag)])

    for mount in spec.ro_mounts:
        cmd.extend(["--ro-mount", str(mount)])
    for mount in spec.rw_mounts:
        cmd.extend(["--rw-mount", str(mount)])

    if spec.setup_script:
        cmd.extend(["--setup-script", str(spec.setup_script)])
    if spec.prepare_snapshot_only:
        cmd.append("--prepare-snapshot-only")
    if spec.project_in_image:
        cmd.append("--project-in-image")

    for entry in spec.env_vars:
        cmd.extend(["--env-var", str(entry)])

    if spec.extra_args:
        cmd.append("--")
        cmd.extend(str(arg) for arg in spec.extra_args)

    return cmd


def compile_agent_process_command(plan: AgentProcessLaunchPlan) -> list[str]:
    if plan.explicit_container_args:
        return [
            str(plan.agent_command),
            *(str(flag) for flag in plan.runtime_flags),
            *(str(arg) for arg in plan.explicit_container_args),
        ]
    if plan.resume and plan.resume_shell_command:
        return ["bash", "-lc", str(plan.resume_shell_command)]
    return [str(plan.agent_command), *(str(flag) for flag in plan.runtime_flags)]


def parse_compiled_agent_cli_command(command: Sequence[str]) -> ParsedLaunchCommand:
    normalized = [str(item) for item in command]
    return ParsedLaunchCommand(
        ro_mounts=tuple(cli_option_values(normalized, long_option="--ro-mount")),
        rw_mounts=tuple(cli_option_values(normalized, long_option="--rw-mount")),
        env_vars=tuple(cli_option_values(normalized, long_option="--env-var")),
        container_args=tuple(_container_args(normalized)),
    )


def compile_docker_run_command(plan: DockerRunInvocationPlan) -> list[str]:
    cmd: list[str] = ["docker", "run"]
    if plan.remove_container:
        cmd.append("--rm")
    if plan.interactive:
        cmd.append("-i")
    if plan.allocate_tty:
        cmd.append("-t")
    cmd.extend(["--tmpfs", str(plan.tmpfs_spec)])
    cmd.extend(str(arg) for arg in plan.run_args)
    cmd.append(str(plan.runtime_image))
    cmd.extend(str(arg) for arg in plan.command)
    return cmd


def _container_args(command: Sequence[str]) -> list[str]:
    for index, token in enumerate(command):
        if token == "--":
            return [str(item) for item in command[index + 1 :]]
    return []


def cli_option_values(args: Sequence[str], *, long_option: str, short_option: str | None = None) -> list[str]:
    values: list[str] = []
    index = 0
    normalized_args = [str(item) for item in args]
    while index < len(normalized_args):
        arg = normalized_args[index]
        if arg == "--":
            break
        if arg == long_option or (short_option and arg == short_option):
            if index + 1 < len(normalized_args):
                values.append(str(normalized_args[index + 1]).strip())
                index += 2
                continue
            index += 1
            continue
        if arg.startswith(f"{long_option}="):
            values.append(str(arg.partition("=")[2]).strip())
            index += 1
            continue
        if short_option and arg.startswith(f"{short_option}="):
            values.append(str(arg.partition("=")[2]).strip())
            index += 1
            continue
        index += 1
    return values


def _cli_option_values(args: Sequence[str], *, long_option: str, short_option: str | None = None) -> list[str]:
    return cli_option_values(args, long_option=long_option, short_option=short_option)
