from __future__ import annotations

import subprocess
import uuid
from collections.abc import Callable
from pathlib import Path
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

    def _build_project_snapshot(self, project_id: str) -> dict[str, Any]:
        _hub_server = _hub_server_module()

        state = self._state.load()
        project = state["projects"].get(project_id)
        if project is None:
            self._state._clear_project_build_request(project_id)
            raise HTTPException(status_code=404, detail="Project not found.")
        if self._state._is_project_build_cancelled(project_id):
            self._state._mark_project_build_cancelled(project_id)
            self._state._clear_project_build_request(project_id)
            current_project = self._state.project(project_id)
            if current_project is None:
                raise HTTPException(status_code=404, detail="Project not found.")
            return current_project

        started_at = _hub_server._iso_now()
        project["build_status"] = "building"
        project["build_error"] = ""
        project["build_started_at"] = started_at
        project["build_finished_at"] = ""
        project["updated_at"] = started_at
        state["projects"][project_id] = project
        self._state.save(state, reason="project_build_started")

        project_copy = dict(project)
        log_path = self._state.project_build_log(project_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        self._state._emit_project_build_log(project_id, "", replace=True)

        try:
            snapshot_tag = self._state._prepare_project_snapshot_for_project(project_copy, log_path=log_path)
            _hub_server.LOGGER.debug(
                "Project build snapshot command succeeded for project=%s snapshot=%s",
                project_id,
                snapshot_tag,
            )
        except Exception as exc:
            state = self._state.load()
            current = state["projects"].get(project_id)
            if current is None:
                self._state._clear_project_build_request(project_id)
                raise
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            now = _hub_server._iso_now()
            is_cancelled = self._state._is_project_build_cancelled(project_id)
            current["build_status"] = "cancelled" if is_cancelled else "failed"
            current["build_error"] = _hub_server.PROJECT_BUILD_CANCELLED_ERROR if is_cancelled else str(detail)
            current["build_finished_at"] = now
            current["updated_at"] = now
            state["projects"][project_id] = current
            if is_cancelled:
                self._state.save(state, reason="project_build_cancelled")
                _hub_server.LOGGER.info("Project build cancelled for project=%s", project_id)
            else:
                self._state.save(state, reason="project_build_failed")
                _hub_server.LOGGER.warning("Project build failed for project=%s: %s", project_id, detail)
            self._state._clear_project_build_request(project_id)
            return current

        state = self._state.load()
        current = state["projects"].get(project_id)
        if current is None:
            self._state._clear_project_build_request(project_id)
            raise HTTPException(status_code=404, detail="Project not found.")
        if self._state._is_project_build_cancelled(project_id):
            now = _hub_server._iso_now()
            current["build_status"] = "cancelled"
            current["build_error"] = _hub_server.PROJECT_BUILD_CANCELLED_ERROR
            current["build_finished_at"] = now
            current["updated_at"] = now
            state["projects"][project_id] = current
            self._state.save(state, reason="project_build_cancelled")
            self._state._clear_project_build_request(project_id)
            return current
        current_candidate = dict(current)
        current_candidate["repo_head_sha"] = project_copy.get("repo_head_sha") or ""
        expected_snapshot = self._state._project_setup_snapshot_tag(current_candidate)
        if snapshot_tag != expected_snapshot:
            current["setup_snapshot_image"] = ""
            current["repo_head_sha"] = ""
            current.pop("snapshot_updated_at", None)
            current["build_status"] = "pending"
            current["build_error"] = ""
            current["build_started_at"] = ""
            current["build_finished_at"] = ""
            current["updated_at"] = _hub_server._iso_now()
            state["projects"][project_id] = current
            self._state.save(state, reason="project_build_superseded")
            _hub_server.LOGGER.debug(
                "Project build output superseded for project=%s built=%s expected=%s; keeping project pending",
                project_id,
                snapshot_tag,
                expected_snapshot,
            )
            return current
        current["setup_snapshot_image"] = snapshot_tag
        current["repo_head_sha"] = project_copy.get("repo_head_sha") or ""
        current["snapshot_updated_at"] = _hub_server._iso_now()
        current["build_status"] = "ready"
        current["build_error"] = ""
        current["build_finished_at"] = _hub_server._iso_now()
        current["updated_at"] = _hub_server._iso_now()
        state["projects"][project_id] = current
        self._state.save(state, reason="project_build_ready")
        _hub_server.LOGGER.debug("Project build completed for project=%s snapshot=%s", project_id, snapshot_tag)
        self._state._clear_project_build_request(project_id)
        return current

    def _ensure_project_setup_snapshot(
        self,
        workspace: Path,
        project: dict[str, Any],
        log_path: Path | None = None,
        project_id: str | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> str:
        _hub_server = _hub_server_module()

        setup_script = str(project.get("setup_script") or "").strip()
        snapshot_tag = self._state._project_setup_snapshot_tag(project)
        resolved_project_id = str(project_id or project.get("id") or "").strip()
        if _hub_server._docker_image_exists(snapshot_tag):
            if log_path is not None:
                line = f"Using cached setup snapshot image '{snapshot_tag}'\n"
                with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
                    log_file.write(line)
                if resolved_project_id:
                    self._state._emit_project_build_log(resolved_project_id, line)
                if on_output is not None:
                    on_output(line)
            return snapshot_tag

        repo_url = str(project.get("repo_url") or "")
        project_tmp_workspace = self._state.project_tmp_workdir(resolved_project_id or str(project.get("id") or ""))
        project_tmp_workspace.mkdir(parents=True, exist_ok=True)
        cmd = self._state._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=_hub_server._container_project_name(project.get("name") or project.get("id")),
            runtime_config_file=self._state.config_file,
            agent_type=_hub_server.DEFAULT_CHAT_AGENT_TYPE,
            run_mode=self._state._runtime_run_mode(),
            agent_tools_url=f"{self._state.artifact_publish_base_url}/api/projects/{resolved_project_id}/agent-tools",
            agent_tools_token="snapshot-token",
            agent_tools_project_id=resolved_project_id,
            repo_url=repo_url,
            project=project,
            snapshot_tag=snapshot_tag,
            ro_mounts=project.get("default_ro_mounts"),
            rw_mounts=project.get("default_rw_mounts"),
            env_vars=project.get("default_env_vars"),
            setup_script=setup_script,
            prepare_snapshot_only=True,
            project_in_image=True,
            runtime_tmp_mount=str(project_tmp_workspace),
            context_key=f"snapshot:{project.get('id')}",
        )
        if log_path is None:
            _hub_server._run(cmd, check=True)
        else:
            emit_build_output: Callable[[str], None] | None = None
            if resolved_project_id or on_output is not None:

                def emit_build_output(chunk: str) -> None:
                    if resolved_project_id:
                        self._state._emit_project_build_log(resolved_project_id, chunk)
                    if on_output is not None:
                        on_output(chunk)

            on_process_start: Callable[[subprocess.Popen[str]], None] | None = None
            if resolved_project_id:

                def on_process_start(process: subprocess.Popen[str]) -> None:
                    self._state._set_project_build_request_process(resolved_project_id, process)

            try:
                _hub_server._run_logged(
                    cmd,
                    log_path=log_path,
                    check=True,
                    on_output=emit_build_output,
                    on_process_start=on_process_start,
                )
            finally:
                if resolved_project_id:
                    self._state._set_project_build_request_process(resolved_project_id, None)
        return snapshot_tag

    def _prepare_project_snapshot_for_project(
        self,
        project: dict[str, Any],
        log_path: Path | None = None,
    ) -> str:
        _hub_server = _hub_server_module()

        project_id = str(project.get("id") or "")
        if project_id and self._state._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=_hub_server.PROJECT_BUILD_CANCELLED_ERROR)
        workspace = self._state._ensure_project_clone(project)
        if project_id and self._state._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=_hub_server.PROJECT_BUILD_CANCELLED_ERROR)
        self._state._sync_checkout_to_remote(workspace, project)
        if project_id and self._state._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=_hub_server.PROJECT_BUILD_CANCELLED_ERROR)
        head_result = _hub_server._run_for_repo(["rev-parse", "HEAD"], workspace, capture=True)
        project["repo_head_sha"] = head_result.stdout.strip()
        return self._state._ensure_project_setup_snapshot(
            workspace,
            project,
            log_path=log_path,
            project_id=str(project.get("id") or ""),
        )

    def _start_project_build_thread_locked(self, project_id: str) -> None:
        _hub_server = _hub_server_module()

        thread = self._state._project_build_threads.get(project_id)
        if thread and thread.is_alive():
            return
        thread = _hub_server.Thread(target=self._project_build_worker, args=(project_id,), daemon=True)
        self._state._project_build_threads[project_id] = thread
        thread.start()

    def _schedule_project_build(self, project_id: str) -> None:
        self._state._register_project_build_request(project_id)
        with self._state._project_build_lock:
            self._start_project_build_thread_locked(project_id)

    def _project_build_worker(self, project_id: str) -> None:
        _hub_server = _hub_server_module()

        try:
            while True:
                if self._state._is_project_build_cancelled(project_id):
                    self._state._mark_project_build_cancelled(project_id)
                    return
                state = self._state.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                build_status = str(project.get("build_status") or "")
                if build_status not in {"pending", "building"}:
                    return
                self._state._build_project_snapshot(project_id)
                state = self._state.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                expected = self._state._project_setup_snapshot_tag(project)
                snapshot = str(project.get("setup_snapshot_image") or "").strip()
                status = str(project.get("build_status") or "")
                if status == "ready" and snapshot == expected and _hub_server._docker_image_exists(snapshot):
                    return
                if status == "pending":
                    if self._state._is_project_build_cancelled(project_id):
                        self._state._mark_project_build_cancelled(project_id)
                        return
                    continue
                if status == "ready" and snapshot != expected:
                    project["build_status"] = "pending"
                    project["updated_at"] = _hub_server._iso_now()
                    state["projects"][project_id] = project
                    self._state.save(state)
                    continue
                return
        finally:
            with self._state._project_build_lock:
                existing = self._state._project_build_threads.get(project_id)
                if existing is not None and existing.ident == _hub_server.current_thread().ident:
                    self._state._project_build_threads.pop(project_id, None)
                    state = self._state.load()
                    project = state["projects"].get(project_id)
                    if project is not None and str(project.get("build_status") or "") in {"pending", "building"}:
                        self._start_project_build_thread_locked(project_id)
            self._state._clear_project_build_request(project_id)

    def _ensure_project_clone(self, project: dict[str, Any]) -> Path:
        _hub_server = _hub_server_module()

        workspace = self._state.project_workdir(project["id"])
        if workspace.exists():
            git_dir = workspace / ".git"
            if git_dir.is_dir():
                return workspace
            self._state._delete_path(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        git_env = self._state._github_git_env_for_repo(
            str(project.get("repo_url") or ""),
            project=project,
            context_key=f"project_clone:{project.get('id')}",
        )
        _hub_server._run(["git", "clone", project["repo_url"], str(workspace)], check=True, env=git_env)
        return workspace

    def _sync_checkout_to_remote(self, workspace: Path, project: dict[str, Any]) -> None:
        _hub_server = _hub_server_module()

        git_env = self._state._github_git_env_for_repo(
            str(project.get("repo_url") or ""),
            project=project,
            context_key=f"project_sync:{project.get('id')}",
        )
        _hub_server._run_for_repo(["fetch", "--all", "--prune"], workspace, check=True, env=git_env)
        branch = str(project.get("default_branch") or "").strip()
        remote_default = _hub_server._git_default_remote_branch(workspace)
        if remote_default:
            branch = remote_default

        if not branch:
            raise _hub_server.ConfigError(
                "Unable to determine remote branch for sync: missing project.default_branch and origin/HEAD."
            )

        if not _hub_server._git_has_remote_branch(workspace, branch):
            raise _hub_server.ConfigError(f"Unable to determine remote branch for sync: origin/{branch} not found.")

        _hub_server._run_for_repo(["checkout", branch], workspace, check=True)
        _hub_server._run_for_repo(["reset", "--hard", f"origin/{branch}"], workspace, check=True)
        _hub_server._run_for_repo(["clean", "-fd"], workspace, check=True)

    def _resolve_project_base_value(self, workspace: Path, project: dict[str, Any]) -> tuple[str, str] | None:
        _hub_server = _hub_server_module()

        base_mode = _hub_server._normalize_base_image_mode(project.get("base_image_mode"))
        base_value = _hub_server._normalize_base_image_value(base_mode, project.get("base_image_value"))

        if base_mode == "tag":
            return "base-image", base_value
        if not base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )

        workspace_root = workspace.resolve()
        base_candidate = Path(base_value)
        resolved_base = base_candidate.resolve() if base_candidate.is_absolute() else (workspace / base_candidate).resolve()
        try:
            resolved_base.relative_to(workspace_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=("Base path must be inside the checked-out project. " f"Got: {base_value}"),
            ) from exc
        if not resolved_base.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Base path does not exist in project workspace: {base_value}",
            )
        if not (resolved_base.is_file() or resolved_base.is_dir()):
            raise HTTPException(
                status_code=400,
                detail=f"Base path must be a file or directory: {base_value}",
            )
        return "base", str(resolved_base)

    def _append_project_base_args(self, cmd: list[str], workspace: Path, project: dict[str, Any]) -> None:
        resolved = self._resolve_project_base_value(workspace, project)
        if not resolved:
            return
        flag, value = resolved
        if flag == "base":
            base_path = Path(value)
            if base_path.is_file():
                cmd.extend(["--base-docker-context", str(workspace.resolve())])
                cmd.extend(["--base-dockerfile", str(base_path)])
                return
        cmd.extend([f"--{flag}", value])

    def _project_setup_snapshot_tag(self, project: dict[str, Any]) -> str:
        _hub_server = _hub_server_module()

        project_id = str(project.get("id") or "")[:12] or "project"
        normalized_base_mode = _hub_server._normalize_base_image_mode(project.get("base_image_mode"))
        normalized_base_value = _hub_server._normalize_base_image_value(
            normalized_base_mode,
            project.get("base_image_value"),
        )
        payload = _hub_server.json.dumps(
            {
                "snapshot_schema_version": _hub_server._snapshot_schema_version(),
                "project_id": project.get("id"),
                "default_branch": project.get("default_branch") or "",
                "repo_head_sha": project.get("repo_head_sha") or "",
                "setup_script": str(project.get("setup_script") or ""),
                "base_mode": normalized_base_mode,
                "base_value": normalized_base_value,
                "default_ro_mounts": list(project.get("default_ro_mounts") or []),
                "default_rw_mounts": list(project.get("default_rw_mounts") or []),
                "default_env_vars": list(project.get("default_env_vars") or []),
                "agent_cli_runtime_inputs_fingerprint": _hub_server._agent_cli_runtime_inputs_fingerprint(),
            },
            sort_keys=True,
        )
        digest = _hub_server.hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"agent-hub-setup-{project_id}-{digest}"

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
