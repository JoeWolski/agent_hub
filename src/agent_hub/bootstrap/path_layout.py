from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HubPathLayoutConfig:
    secrets_dir_name: str
    openai_credentials_file_name: str
    openai_codex_auth_file_name: str
    agent_tools_mcp_runtime_dir_name: str
    agent_tools_mcp_runtime_file_name: str
    state_file_name: str
    agent_capabilities_cache_file_name: str
    runtime_tmp_root_dir_name: str
    runtime_tmp_projects_dir_name: str
    artifact_storage_dir_name: str
    artifact_storage_chat_dir_name: str
    artifact_storage_session_dir_name: str
    chat_runtime_configs_dir_name: str
    github_app_settings_file_name: str
    github_app_installation_file_name: str
    github_tokens_file_name: str
    gitlab_tokens_file_name: str
    git_credentials_dir_name: str


@dataclass(frozen=True)
class HubPathLayout:
    data_dir: Path
    secrets_dir: Path
    openai_credentials_file: Path
    host_agent_home: Path
    host_codex_dir: Path
    agent_tools_mcp_runtime_script: Path
    openai_codex_auth_file: Path
    state_file: Path
    agent_capabilities_cache_file: Path
    project_dir: Path
    chat_dir: Path
    log_dir: Path
    runtime_tmp_dir: Path
    runtime_project_tmp_dir: Path
    artifacts_dir: Path
    chat_artifacts_dir: Path
    session_artifacts_dir: Path
    chat_runtime_configs_dir: Path
    github_app_settings_file: Path
    github_app_installation_file: Path
    github_tokens_file: Path
    gitlab_tokens_file: Path
    git_credentials_dir: Path
    directories_to_create: tuple[Path, ...]


def build_hub_path_layout(*, data_dir: Path, local_user: str, config: HubPathLayoutConfig) -> HubPathLayout:
    resolved_data_dir = Path(data_dir).resolve()
    secrets_dir = resolved_data_dir / config.secrets_dir_name
    openai_credentials_file = secrets_dir / config.openai_credentials_file_name
    host_agent_home = (resolved_data_dir / "agent-home" / local_user).resolve()
    host_codex_dir = host_agent_home / ".codex"
    agent_tools_mcp_runtime_script = (
        host_codex_dir / config.agent_tools_mcp_runtime_dir_name / config.agent_tools_mcp_runtime_file_name
    )
    openai_codex_auth_file = host_codex_dir / config.openai_codex_auth_file_name
    state_file = resolved_data_dir / config.state_file_name
    agent_capabilities_cache_file = resolved_data_dir / config.agent_capabilities_cache_file_name
    project_dir = resolved_data_dir / "projects"
    chat_dir = resolved_data_dir / "chats"
    log_dir = resolved_data_dir / "logs"
    runtime_tmp_dir = resolved_data_dir / config.runtime_tmp_root_dir_name
    runtime_project_tmp_dir = runtime_tmp_dir / config.runtime_tmp_projects_dir_name
    artifacts_dir = resolved_data_dir / config.artifact_storage_dir_name
    chat_artifacts_dir = artifacts_dir / config.artifact_storage_chat_dir_name
    session_artifacts_dir = artifacts_dir / config.artifact_storage_session_dir_name
    chat_runtime_configs_dir = resolved_data_dir / config.chat_runtime_configs_dir_name
    github_app_settings_file = secrets_dir / config.github_app_settings_file_name
    github_app_installation_file = secrets_dir / config.github_app_installation_file_name
    github_tokens_file = secrets_dir / config.github_tokens_file_name
    gitlab_tokens_file = secrets_dir / config.gitlab_tokens_file_name
    git_credentials_dir = secrets_dir / config.git_credentials_dir_name
    directories_to_create = (
        resolved_data_dir,
        project_dir,
        chat_dir,
        log_dir,
        runtime_tmp_dir,
        runtime_project_tmp_dir,
        artifacts_dir,
        chat_artifacts_dir,
        session_artifacts_dir,
        secrets_dir,
        chat_runtime_configs_dir,
        git_credentials_dir,
        host_codex_dir,
    )
    return HubPathLayout(
        data_dir=resolved_data_dir,
        secrets_dir=secrets_dir,
        openai_credentials_file=openai_credentials_file,
        host_agent_home=host_agent_home,
        host_codex_dir=host_codex_dir,
        agent_tools_mcp_runtime_script=agent_tools_mcp_runtime_script,
        openai_codex_auth_file=openai_codex_auth_file,
        state_file=state_file,
        agent_capabilities_cache_file=agent_capabilities_cache_file,
        project_dir=project_dir,
        chat_dir=chat_dir,
        log_dir=log_dir,
        runtime_tmp_dir=runtime_tmp_dir,
        runtime_project_tmp_dir=runtime_project_tmp_dir,
        artifacts_dir=artifacts_dir,
        chat_artifacts_dir=chat_artifacts_dir,
        session_artifacts_dir=session_artifacts_dir,
        chat_runtime_configs_dir=chat_runtime_configs_dir,
        github_app_settings_file=github_app_settings_file,
        github_app_installation_file=github_app_installation_file,
        github_tokens_file=github_tokens_file,
        gitlab_tokens_file=gitlab_tokens_file,
        git_credentials_dir=git_credentials_dir,
        directories_to_create=directories_to_create,
    )


def ensure_hub_path_layout_dirs(layout: HubPathLayout) -> None:
    for path in layout.directories_to_create:
        path.mkdir(parents=True, exist_ok=True)

