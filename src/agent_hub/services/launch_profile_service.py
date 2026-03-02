from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from agent_core import DEFAULT_RUNTIME_RUN_MODE
from agent_core import launch as core_launch


def _server_module() -> Any:
    import agent_hub.server as server_module

    return server_module


class LaunchProfileService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def _runtime_identity_for_workspace(self, workspace: Path) -> tuple[int, int, str]:
        del workspace
        return int(self._state.local_uid), int(self._state.local_gid), self._state.local_supp_gids

    def _runtime_run_mode(self) -> str:
        if self._state.runtime_config is None:
            return DEFAULT_RUNTIME_RUN_MODE
        return str(self._state.runtime_config.runtime.run_mode or DEFAULT_RUNTIME_RUN_MODE)

    def _chat_snapshot_ready(self, project: dict[str, Any]) -> tuple[bool, str]:
        server_module = _server_module()
        snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
        expected_snapshot_tag = self._state._project_setup_snapshot_tag(project)
        snapshot_ready = (
            str(project.get("build_status") or "") == "ready"
            and snapshot_tag
            and snapshot_tag == expected_snapshot_tag
            and server_module._docker_image_exists(snapshot_tag)
        )
        return snapshot_ready, snapshot_tag

    def assert_chat_snapshot_ready(self, project: dict[str, Any]) -> str:
        snapshot_ready, snapshot_tag = self._chat_snapshot_ready(project)
        if not snapshot_ready:
            raise HTTPException(status_code=409, detail="Project image is not ready yet. Wait for setup build to finish.")
        return snapshot_tag

    def prepare_chat_launch_context(
        self,
        *,
        chat_id: str,
        chat: dict[str, Any],
        project: dict[str, Any],
        resume: bool,
        agent_tools_token: str,
        artifact_publish_token: str,
        ready_ack_guid: str,
        context_key: str,
    ) -> dict[str, Any]:
        server_module = _server_module()
        snapshot_tag = self.assert_chat_snapshot_ready(project)

        workspace = self._state._ensure_chat_clone(chat, project)
        self._state._sync_checkout_to_remote(workspace, project)
        container_project_name = server_module._container_project_name(project.get("name") or project.get("id"))
        container_workspace = server_module._container_workspace_path_for_project(project.get("name") or project.get("id"))
        agent_type = server_module._normalize_chat_agent_type(chat.get("agent_type"), strict=True)
        agent_tools_url = self._state._chat_agent_tools_url(chat_id)
        project_id = str(project.get("id") or "")
        runtime_config_file = self._state._prepare_chat_runtime_config(
            chat_id,
            agent_type=agent_type,
            agent_tools_url=agent_tools_url,
            agent_tools_token=agent_tools_token,
            agent_tools_project_id=project_id,
            agent_tools_chat_id=chat_id,
            trusted_project_path=container_workspace,
        )

        agent_args = [str(arg) for arg in (chat.get("agent_args") or []) if str(arg).strip()]
        if resume and agent_type == server_module.AGENT_TYPE_CODEX:
            # agent_cli resume mode and explicit args are mutually exclusive.
            agent_args = []
        elif resume:
            agent_args = self._state._resume_agent_args(agent_type, agent_args)

        chat_tmp_workspace = self._state.chat_tmp_workdir(project_id, chat_id)
        chat_tmp_workspace.mkdir(parents=True, exist_ok=True)

        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=container_project_name,
            runtime_config_file=runtime_config_file,
            agent_type=agent_type,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=agent_tools_url,
            agent_tools_token=agent_tools_token,
            agent_tools_project_id=project_id,
            agent_tools_chat_id=chat_id,
            repo_url=str(project.get("repo_url") or ""),
            project=project,
            snapshot_tag=snapshot_tag,
            ro_mounts=chat.get("ro_mounts"),
            rw_mounts=chat.get("rw_mounts"),
            env_vars=chat.get("env_vars"),
            artifacts_url=self._state._chat_artifact_publish_url(chat_id),
            artifacts_token=artifact_publish_token,
            ready_ack_guid=ready_ack_guid,
            resume=resume,
            project_in_image=True,
            runtime_tmp_mount=str(chat_tmp_workspace),
            context_key=context_key,
            extra_args=agent_args,
        )
        return {
            "workspace": workspace,
            "runtime_config_file": runtime_config_file,
            "container_project_name": container_project_name,
            "container_workspace": container_workspace,
            "agent_type": agent_type,
            "snapshot_tag": snapshot_tag,
            "project_id": project_id,
            "command": cmd,
        }

    def _prepare_agent_cli_command(
        self,
        *,
        workspace: Path,
        container_project_name: str,
        runtime_config_file: Path,
        agent_type: str,
        run_mode: str,
        agent_tools_url: str,
        agent_tools_token: str,
        agent_tools_project_id: str = "",
        agent_tools_chat_id: str = "",
        ready_ack_guid: str = "",
        repo_url: str = "",
        project: dict[str, Any] | None = None,
        snapshot_tag: str = "",
        ro_mounts: list[str] | None = None,
        rw_mounts: list[str] | None = None,
        env_vars: list[str] | None = None,
        artifacts_url: str = "",
        artifacts_token: str = "",
        resume: bool = False,
        allocate_tty: bool = True,
        context_key: str = "",
        extra_args: list[str] | None = None,
        setup_script: str = "",
        prepare_snapshot_only: bool = False,
        project_in_image: bool = False,
        runtime_tmp_mount: str = "",
    ) -> list[str]:
        del context_key, repo_url
        server_module = _server_module()
        runtime_uid, runtime_gid, runtime_supp_gids = self._runtime_identity_for_workspace(workspace)
        normalized_agent_type = server_module._normalize_chat_agent_type(agent_type, strict=True)
        agent_command = server_module._agent_command_for_type(normalized_agent_type)
        project_base_args: list[str] = []
        if snapshot_tag:
            self._state._append_project_base_args(project_base_args, workspace, project)

        normalized_ro_mounts = [str(mount) for mount in (ro_mounts or []) if str(mount or "").strip()]
        normalized_rw_mounts = [str(mount) for mount in (rw_mounts or []) if str(mount or "").strip()]
        normalized_runtime_tmp_mount = str(runtime_tmp_mount or "").strip()
        if normalized_runtime_tmp_mount:
            has_workspace_tmp_mount = server_module._contains_container_mount_target(
                [*normalized_ro_mounts, *normalized_rw_mounts],
                server_module.DEFAULT_CONTAINER_TMP_DIR,
            )
            if not has_workspace_tmp_mount:
                normalized_rw_mounts.append(f"{normalized_runtime_tmp_mount}:{server_module.DEFAULT_CONTAINER_TMP_DIR}")

        command_env_vars: list[str] = []
        if artifacts_url:
            command_env_vars.append(f"AGENT_ARTIFACTS_URL={artifacts_url}")
        if artifacts_token:
            command_env_vars.append(f"AGENT_ARTIFACT_TOKEN={artifacts_token}")

        command_env_vars.append(f"{server_module.AGENT_TOOLS_URL_ENV}={agent_tools_url}")
        command_env_vars.append(f"{server_module.AGENT_TOOLS_TOKEN_ENV}={agent_tools_token}")
        command_env_vars.append(f"{server_module.AGENT_TOOLS_PROJECT_ID_ENV}={agent_tools_project_id}")
        command_env_vars.append(f"{server_module.AGENT_TOOLS_CHAT_ID_ENV}={agent_tools_chat_id}")
        if normalized_runtime_tmp_mount:
            command_env_vars.append(f"{server_module.AGENT_HUB_TMP_HOST_PATH_ENV}={normalized_runtime_tmp_mount}")
        normalized_ready_ack_guid = str(ready_ack_guid or "").strip()
        if normalized_ready_ack_guid:
            command_env_vars.append(f"{server_module.AGENT_TOOLS_READY_ACK_GUID_ENV}={normalized_ready_ack_guid}")
        for env_entry in self._state._git_identity_env_vars_from_settings():
            command_env_vars.append(env_entry)

        for env_entry in env_vars or []:
            if server_module._is_reserved_env_entry(str(env_entry)):
                continue
            if str(env_entry).split("=", 1)[0].strip() == server_module.AGENT_HUB_TMP_HOST_PATH_ENV:
                continue
            command_env_vars.append(str(env_entry))

        spec = core_launch.LaunchSpec(
            repo_root=server_module._repo_root(),
            workspace=workspace,
            container_project_name=container_project_name,
            agent_home_path=self._state.host_agent_home,
            runtime_config_file=runtime_config_file,
            system_prompt_file=self._state.system_prompt_file,
            agent_command=agent_command,
            run_mode=str(run_mode),
            local_uid=int(runtime_uid),
            local_gid=int(runtime_gid),
            local_user=self._state.local_user,
            local_supplementary_gids=runtime_supp_gids,
            allocate_tty=allocate_tty,
            resume=bool(resume and normalized_agent_type == server_module.AGENT_TYPE_CODEX),
            snapshot_tag=str(snapshot_tag or ""),
            ro_mounts=tuple(normalized_ro_mounts),
            rw_mounts=tuple(normalized_rw_mounts),
            env_vars=tuple(command_env_vars),
            extra_args=tuple(str(arg) for arg in (extra_args or [])),
            openai_credentials_args=tuple(self._state._openai_credentials_arg()),
            base_args=tuple(project_base_args),
            setup_script=str(setup_script or ""),
            prepare_snapshot_only=prepare_snapshot_only,
            project_in_image=project_in_image,
        )
        return core_launch.compile_agent_cli_command(spec)

    def _launch_profile_from_command(
        self,
        *,
        mode: str,
        command: list[str],
        workspace: Path,
        runtime_config_file: Path,
        container_project_name: str,
        agent_type: str,
        snapshot_tag: str,
        prepare_snapshot_only: bool,
    ) -> dict[str, Any]:
        server_module = _server_module()
        runtime_image = ""
        if snapshot_tag:
            runtime_image = str(snapshot_tag)
            if prepare_snapshot_only:
                runtime_image = str(server_module._snapshot_setup_runtime_image_for_snapshot(snapshot_tag))
        parsed = core_launch.parse_compiled_agent_cli_command(command)

        return {
            "mode": str(mode or "").strip(),
            "generated_at": server_module._iso_now(),
            "workspace": str(workspace),
            "runtime_config_file": str(runtime_config_file),
            "container_project_name": str(container_project_name),
            "agent_type": server_module._normalize_chat_agent_type(agent_type, strict=True),
            "snapshot_tag": str(snapshot_tag or ""),
            "runtime_image": runtime_image,
            "prepare_snapshot_only": bool(prepare_snapshot_only),
            "ro_mounts": list(parsed.ro_mounts),
            "rw_mounts": list(parsed.rw_mounts),
            "env_vars": list(parsed.env_vars),
            "container_args": list(parsed.container_args),
            "command": [str(item) for item in command],
        }

    def project_snapshot_launch_profile(self, project_id: str) -> dict[str, Any]:
        server_module = _server_module()
        state = self._state.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        workspace = self._state._ensure_project_clone(project)
        self._state._sync_checkout_to_remote(workspace, project)
        head_result = server_module._run_for_repo(["rev-parse", "HEAD"], workspace, capture=True)
        project_for_launch = dict(project)
        project_for_launch["repo_head_sha"] = head_result.stdout.strip()
        snapshot_tag = self._state._project_setup_snapshot_tag(project_for_launch)
        resolved_project_id = str(project_for_launch.get("id") or project_id).strip()
        project_tmp_workspace = self._state.project_tmp_workdir(resolved_project_id)
        project_tmp_workspace.mkdir(parents=True, exist_ok=True)
        container_project_name = server_module._container_project_name(
            project_for_launch.get("name") or project_for_launch.get("id")
        )
        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=container_project_name,
            runtime_config_file=self._state.config_file,
            agent_type=server_module.DEFAULT_CHAT_AGENT_TYPE,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=f"{self._state.artifact_publish_base_url}/api/projects/{resolved_project_id}/agent-tools",
            agent_tools_token="snapshot-token",
            agent_tools_project_id=resolved_project_id,
            repo_url=str(project_for_launch.get("repo_url") or ""),
            project=project_for_launch,
            snapshot_tag=snapshot_tag,
            ro_mounts=project_for_launch.get("default_ro_mounts"),
            rw_mounts=project_for_launch.get("default_rw_mounts"),
            env_vars=project_for_launch.get("default_env_vars"),
            setup_script=str(project_for_launch.get("setup_script") or ""),
            prepare_snapshot_only=True,
            project_in_image=True,
            runtime_tmp_mount=str(project_tmp_workspace),
            context_key=f"snapshot:{project_for_launch.get('id')}",
        )
        return self._launch_profile_from_command(
            mode="project_snapshot",
            command=cmd,
            workspace=workspace,
            runtime_config_file=self._state.config_file,
            container_project_name=container_project_name,
            agent_type=server_module.DEFAULT_CHAT_AGENT_TYPE,
            snapshot_tag=snapshot_tag,
            prepare_snapshot_only=True,
        )

    def chat_launch_profile(
        self,
        chat_id: str,
        *,
        resume: bool = False,
        agent_tools_token: str = "agent-tools-token",
        artifact_publish_token: str = "artifact-token",
        ready_ack_guid: str = "ready-ack-guid",
    ) -> dict[str, Any]:
        state = self._state.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat.get("project_id"))
        if project is None:
            raise HTTPException(status_code=404, detail="Parent project missing.")

        launch_context = self.prepare_chat_launch_context(
            chat_id=chat_id,
            chat=chat,
            project=project,
            resume=resume,
            agent_tools_token=agent_tools_token,
            artifact_publish_token=artifact_publish_token,
            ready_ack_guid=ready_ack_guid,
            context_key=f"chat_launch_profile:{chat_id}",
        )
        return self._launch_profile_from_command(
            mode="chat_start",
            command=launch_context["command"],
            workspace=launch_context["workspace"],
            runtime_config_file=launch_context["runtime_config_file"],
            container_project_name=launch_context["container_project_name"],
            agent_type=launch_context["agent_type"],
            snapshot_tag=launch_context["snapshot_tag"],
            prepare_snapshot_only=False,
        )


__all__ = ["LaunchProfileService"]
