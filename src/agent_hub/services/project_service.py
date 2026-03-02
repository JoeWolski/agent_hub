from __future__ import annotations

import subprocess
import uuid
from typing import Any

from fastapi import HTTPException


def _hub_server_module() -> Any:
    import agent_hub.server as _hub_server

    return _hub_server


class ProjectService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def add_project(
        self,
        repo_url: str,
        name: str | None = None,
        default_branch: str | None = None,
        setup_script: str | None = None,
        base_image_mode: str | None = None,
        base_image_value: str | None = None,
        default_ro_mounts: list[str] | None = None,
        default_rw_mounts: list[str] | None = None,
        default_env_vars: list[str] | None = None,
        credential_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _hub_server = _hub_server_module()

        normalized_repo_url = str(repo_url or "").strip()
        validation_error = _hub_server._project_repo_url_validation_error(normalized_repo_url)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        state = self._state.load()
        project_id = uuid.uuid4().hex
        project_name = name or _hub_server._extract_repo_name(normalized_repo_url)
        normalized_binding = self._state._auto_discover_project_credential_binding(
            normalized_repo_url,
            credential_binding=credential_binding,
        )
        normalized_env_vars = self._state._dedupe_entries(default_env_vars or [])
        auth_env_vars = self._state._recommended_auth_env_vars_for_repo(
            normalized_repo_url,
            credential_binding=normalized_binding,
        )
        existing_env_keys = {
            str(entry).split("=", 1)[0].strip().upper()
            for entry in normalized_env_vars
            if "=" in str(entry)
        }
        github_token_value = ""
        for entry in normalized_env_vars:
            raw = str(entry)
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            normalized_key = key.strip().upper()
            if normalized_key in {"GITHUB_TOKEN", "GH_TOKEN"} and value:
                github_token_value = value
                break
        if not github_token_value:
            for entry in auth_env_vars:
                raw = str(entry)
                if "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                normalized_key = key.strip().upper()
                if normalized_key in {"GITHUB_TOKEN", "GH_TOKEN"} and value:
                    github_token_value = value
                    break
        if github_token_value:
            if "GITHUB_TOKEN" not in existing_env_keys:
                normalized_env_vars.append(f"GITHUB_TOKEN={github_token_value}")
                existing_env_keys.add("GITHUB_TOKEN")
            if "GH_TOKEN" not in existing_env_keys:
                normalized_env_vars.append(f"GH_TOKEN={github_token_value}")
                existing_env_keys.add("GH_TOKEN")
        for auth_env in auth_env_vars:
            auth_key = str(auth_env).split("=", 1)[0].strip().upper()
            if auth_key in {"GITHUB_TOKEN", "GH_TOKEN"}:
                continue
            if auth_key and auth_key not in existing_env_keys:
                normalized_env_vars.append(auth_env)
                existing_env_keys.add(auth_key)
        resolved_default_branch = str(default_branch or "").strip()
        if not resolved_default_branch:
            git_env = self._state._github_git_env_for_repo(
                normalized_repo_url,
                project={"repo_url": normalized_repo_url, "credential_binding": normalized_binding},
            )
            resolved_default_branch = _hub_server._detect_default_branch(normalized_repo_url, env=git_env)
        normalized_base_mode = _hub_server._normalize_base_image_mode(base_image_mode)
        normalized_base_value = _hub_server._normalize_base_image_value(normalized_base_mode, base_image_value)
        if normalized_base_mode == "repo_path" and not normalized_base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )
        project = {
            "id": project_id,
            "name": project_name,
            "repo_url": normalized_repo_url,
            "setup_script": setup_script or "",
            "base_image_mode": normalized_base_mode,
            "base_image_value": normalized_base_value,
            "default_ro_mounts": default_ro_mounts or [],
            "default_rw_mounts": default_rw_mounts or [],
            "default_env_vars": normalized_env_vars,
            "default_branch": resolved_default_branch,
            "created_at": _hub_server._iso_now(),
            "updated_at": _hub_server._iso_now(),
            "setup_snapshot_image": "",
            "build_status": "pending",
            "build_error": "",
            "build_started_at": "",
            "build_finished_at": "",
            "credential_binding": normalized_binding,
        }
        state["projects"][project_id] = project
        self._state.save(state)
        self._state._schedule_project_build(project_id)
        return self._state.load()["projects"][project_id]

    def create_project(self, **kwargs: Any) -> dict[str, Any]:
        return self.add_project(**kwargs)

    def update_project(self, project_id: str, update: dict[str, Any]) -> dict[str, Any]:
        _hub_server = _hub_server_module()

        state = self._state.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        for field in [
            "setup_script",
            "default_branch",
            "name",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
            "credential_binding",
        ]:
            if field in update:
                project[field] = update[field]
        normalized_base_mode = _hub_server._normalize_base_image_mode(project.get("base_image_mode"))
        normalized_base_value = _hub_server._normalize_base_image_value(
            normalized_base_mode, project.get("base_image_value")
        )
        if normalized_base_mode == "repo_path" and not normalized_base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )
        project["base_image_mode"] = normalized_base_mode
        project["base_image_value"] = normalized_base_value

        snapshot_fields = {
            "setup_script",
            "default_branch",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
        }
        requires_rebuild = any(field in update for field in snapshot_fields)
        if requires_rebuild:
            project["setup_snapshot_image"] = ""
            project["repo_head_sha"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""

        project["updated_at"] = _hub_server._iso_now()
        state["projects"][project_id] = project
        self._state.save(state)
        if requires_rebuild:
            self._state._schedule_project_build(project_id)
            return self._state.load()["projects"][project_id]
        return self._state.load()["projects"][project_id]

    def credential_binding_payload(self, project_id: str) -> dict[str, Any]:
        return self._state.project_credential_binding_payload(project_id)

    def attach_project_credentials(self, *, project_id: str, mode: Any, credential_ids: Any, source: str) -> dict[str, Any]:
        return self._state.attach_project_credentials(
            project_id=project_id,
            mode=mode,
            credential_ids=credential_ids,
            source=source,
        )

    def delete_project(self, project_id: str) -> None:
        _hub_server = _hub_server_module()

        state = self._state.load()
        if project_id not in state["projects"]:
            raise HTTPException(status_code=404, detail="Project not found.")

        process_to_cancel: subprocess.Popen[str] | None = None
        with self._state._project_build_requests_lock:
            request_state = self._state._project_build_requests.pop(project_id, None)
            if request_state is not None:
                process_to_cancel = request_state.process
        if process_to_cancel is not None and _hub_server._is_process_running(process_to_cancel.pid):
            _hub_server._stop_process(process_to_cancel.pid)

        project_chats = [chat for chat in self._state.list_chats() if chat["project_id"] == project_id]
        for chat in project_chats:
            self._state.delete_chat(chat["id"], state=state)

        project_workspace = self._state.project_workdir(project_id)
        if project_workspace.exists():
            self._state._delete_path(project_workspace)
        project_log = self._state.project_build_log(project_id)
        if project_log.exists():
            project_log.unlink()

        del state["projects"][project_id]
        self._state.save(state)

    def cancel_project_build(self, project_id: str) -> dict[str, Any]:
        return self._state.cancel_project_build(project_id)

    def project_build_logs(self, project_id: str) -> str:
        project = self._state.project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        log_path = self._state.project_build_log(project_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    def project_launch_profile(self, project_id: str) -> dict[str, Any]:
        return self._state.project_snapshot_launch_profile(project_id)

    def create_and_start_chat(
        self,
        project_id: str,
        *,
        agent_args: list[str] | None = None,
        agent_type: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        _hub_server = _hub_server_module()

        state = self._state.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        build_status = str(project.get("build_status") or "")
        if build_status != "ready":
            raise HTTPException(status_code=409, detail="Project image is still being built. Save settings and wait.")
        normalized_agent_args = [str(arg) for arg in (agent_args or []) if str(arg).strip()]
        resolved_agent_type = (
            self._state.default_chat_agent_type()
            if agent_type is None
            else _hub_server._normalize_chat_agent_type(agent_type, strict=True)
        )
        normalized_agent_args = _hub_server._apply_default_model_for_agent(
            resolved_agent_type,
            normalized_agent_args,
            self._state.runtime_config,
        )
        normalized_request_id = _hub_server._compact_whitespace(str(request_id or "")).strip()
        if normalized_request_id:
            existing_chat = self._state._chat_for_create_request(
                state=state,
                project_id=project_id,
                request_id=normalized_request_id,
            )
            if existing_chat is not None:
                _hub_server.LOGGER.info(
                    "Reused existing chat for create request project_id=%s request_id=%s chat_id=%s",
                    project_id,
                    normalized_request_id,
                    existing_chat.get("id"),
                )
                return existing_chat
        create_chat_kwargs: dict[str, Any] = {
            "profile": "",
            "ro_mounts": list(project.get("default_ro_mounts") or []),
            "rw_mounts": list(project.get("default_rw_mounts") or []),
            "env_vars": list(project.get("default_env_vars") or []),
            "agent_args": normalized_agent_args,
            "agent_type": resolved_agent_type,
        }
        if normalized_request_id:
            create_chat_kwargs["create_request_id"] = normalized_request_id
        chat = self._state.create_chat(
            project_id,
            **create_chat_kwargs,
        )
        return self._state.start_chat(chat["id"])


__all__ = ["ProjectService"]
