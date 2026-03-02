from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from threading import Thread
from typing import Any, Callable

from fastapi import HTTPException


def _server_module() -> Any:
    import agent_hub.server as server_module

    return server_module


class AutoConfigService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def _run_temporary_auto_config_chat(
        self,
        workspace: Path,
        repo_url: str,
        branch: str,
        agent_type: str = "codex",
        agent_args: list[str] | None = None,
        on_output: Callable[[str], None] | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        server_module = _server_module()
        normalized_request_id = self._state._normalize_auto_config_request_id(request_id)
        resolved_agent_type = server_module._normalize_chat_agent_type(agent_type, strict=True)
        normalized_agent_args = [str(arg) for arg in (agent_args or []) if str(arg).strip()]

        def emit(chunk: str) -> None:
            if on_output is None:
                return
            text = str(chunk or "")
            if not text:
                return
            try:
                on_output(text)
            except Exception:
                server_module.LOGGER.exception("Auto-config output callback failed.")

        if resolved_agent_type == server_module.AGENT_TYPE_CODEX:
            account_connected, _ = server_module._read_codex_auth(self._state.openai_codex_auth_file)
            if not account_connected:
                raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_NOT_CONNECTED_ERROR)

        prompt = self._state._auto_config_prompt(repo_url, branch)
        output_file = workspace / f".agent-hub-auto-config-{uuid.uuid4().hex}.json"
        container_project_name = server_module._container_project_name(server_module._extract_repo_name(repo_url) or "auto-config")
        container_workspace = str(PurePosixPath(server_module.DEFAULT_CONTAINER_HOME) / container_project_name)
        container_output_file = str(PurePosixPath(container_workspace) / output_file.name)
        session_id, session_token = self._state._create_agent_tools_session(repo_url=repo_url, workspace=workspace)
        ready_ack_guid = self._state.issue_agent_tools_session_ready_ack_guid(session_id)
        agent_tools_url = f"{self._state.artifact_publish_base_url}/api/agent-tools/sessions/{session_id}"
        agent_tools_chat_id = f"auto-config:{session_id}"
        runtime_config_file = self._state._prepare_chat_runtime_config(
            f"auto-config-{session_id}",
            agent_type=resolved_agent_type,
            agent_tools_url=agent_tools_url,
            agent_tools_token=session_token,
            agent_tools_project_id="",
            agent_tools_chat_id=agent_tools_chat_id,
            trusted_project_path=container_workspace,
        )
        artifact_publish_token = server_module._new_artifact_publish_token()
        with self._state._agent_tools_sessions_lock:
            active_session = self._state._agent_tools_sessions.get(session_id)
            if active_session is not None:
                active_session["artifact_publish_token_hash"] = server_module._hash_artifact_publish_token(
                    artifact_publish_token
                )
                self._state._agent_tools_sessions[session_id] = active_session

        extra_args = [
            *normalized_agent_args,
            "exec",
            "--skip-git-repo-check",
            "--cd",
            container_workspace,
            "--sandbox",
            "workspace-write",
            "--output-last-message",
            container_output_file,
            prompt,
        ]
        cmd = self._state._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=container_project_name,
            runtime_config_file=runtime_config_file,
            agent_type=resolved_agent_type,
            run_mode=self._state._runtime_run_mode(),
            agent_tools_url=agent_tools_url,
            agent_tools_token=session_token,
            agent_tools_project_id="",
            agent_tools_chat_id=agent_tools_chat_id,
            repo_url=repo_url,
            artifacts_url=f"{self._state.artifact_publish_base_url}/api/agent-tools/sessions/{session_id}/artifacts/publish",
            artifacts_token=artifact_publish_token,
            ready_ack_guid=ready_ack_guid,
            allocate_tty=False,
            context_key=f"auto_config_chat:{session_id}",
            extra_args=extra_args,
        )
        emit("Launching temporary repository analysis chat...\n")
        emit(f"Working directory: {workspace}\n")
        emit(f"Repository URL: {repo_url}\n")
        emit(f"Branch: {branch}\n\n")

        if self._state._is_auto_config_request_cancelled(normalized_request_id):
            raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR)

        try:
            process = subprocess.Popen(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                start_new_session=True,
            )
            self._state._set_auto_config_request_process(normalized_request_id, process)
        except OSError as exc:
            try:
                runtime_config_file.unlink()
            except OSError:
                pass
            self._state._remove_agent_tools_session(session_id)
            raise HTTPException(status_code=502, detail=f"Temporary auto-config chat failed to start: {exc}") from exc

        output_chunks: list[str] = []

        def consume_output() -> None:
            stdout = process.stdout
            if stdout is None:
                return
            try:
                for line in iter(stdout.readline, ""):
                    if line == "":
                        break
                    output_chunks.append(line)
                    emit(line)
            finally:
                stdout.close()

        try:
            try:
                consumer = Thread(target=consume_output, daemon=True)
                consumer.start()
                return_code = process.wait(timeout=max(20.0, float(server_module.AUTO_CONFIG_CHAT_TIMEOUT_SECONDS)))
                consumer.join(timeout=2.0)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
                emit("\nTemporary auto-config chat timed out.\n")
                if self._state._is_auto_config_request_cancelled(normalized_request_id):
                    raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR) from exc
                raise HTTPException(status_code=504, detail="Temporary auto-config chat timed out.") from exc

            output_text = "".join(output_chunks).strip()
            if return_code != 0:
                if self._state._is_auto_config_request_cancelled(normalized_request_id):
                    emit("\nAuto-config chat was cancelled by user.\n")
                    raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR)
                detail = server_module._codex_exec_error_message_full(output_text)
                raise HTTPException(status_code=502, detail=f"Temporary auto-config chat failed: {detail}")

            try:
                raw_payload_text = output_file.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError as exc:
                raise HTTPException(status_code=502, detail=server_module.AUTO_CONFIG_MISSING_OUTPUT_ERROR) from exc
            if not raw_payload_text:
                raise HTTPException(status_code=502, detail=server_module.AUTO_CONFIG_MISSING_OUTPUT_ERROR)

            try:
                parsed_payload = server_module._parse_json_object_from_text(raw_payload_text)
            except ValueError as exc:
                raise HTTPException(status_code=502, detail=server_module.AUTO_CONFIG_INVALID_OUTPUT_ERROR) from exc
            return {
                "payload": parsed_payload,
                "model": server_module._auto_config_analysis_model(resolved_agent_type, normalized_agent_args),
                "agent_type": resolved_agent_type,
                "agent_args": normalized_agent_args,
            }
        finally:
            self._state._set_auto_config_request_process(normalized_request_id, None)
            try:
                output_file.unlink()
            except OSError:
                pass
            try:
                runtime_config_file.unlink()
            except OSError:
                pass
            self._state._remove_agent_tools_session(session_id)

    def auto_configure_project(
        self,
        *,
        repo_url: Any,
        default_branch: Any = None,
        request_id: Any = None,
        agent_type: Any = None,
        agent_args: Any = None,
    ) -> dict[str, Any]:
        server_module = _server_module()
        normalized_repo_url = str(repo_url or "").strip()
        validation_error = server_module._project_repo_url_validation_error(normalized_repo_url)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)
        resolved_agent_type = server_module._resolve_optional_chat_agent_type(
            agent_type,
            default_value=self._state.default_chat_agent_type(),
        )
        if agent_args is None:
            normalized_agent_args: list[str] = []
        elif isinstance(agent_args, list):
            normalized_agent_args = [str(arg) for arg in agent_args if str(arg).strip()]
        else:
            raise HTTPException(status_code=400, detail="agent_args must be an array.")
        normalized_request_id = str(request_id or "").strip()[: server_module.AUTO_CONFIG_REQUEST_ID_MAX_CHARS]
        if normalized_request_id:
            self._state._register_auto_config_request(normalized_request_id)
            if self._state._is_auto_config_request_cancelled(normalized_request_id):
                self._state._clear_auto_config_request(normalized_request_id)
                raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR)

        def emit_auto_config_log(text: str, replace: bool = False) -> None:
            if not normalized_request_id:
                return
            self._state._emit_auto_config_log(normalized_request_id, text, replace=replace)

        requested_branch = str(default_branch or "").strip()
        git_env = self._state._github_git_env_for_repo(normalized_repo_url)
        sanitized_git_env = {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
        authenticated_git_env = dict(sanitized_git_env)
        authenticated_git_env.update(git_env)
        resolved_branch = requested_branch or server_module._detect_default_branch(
            normalized_repo_url,
            env=authenticated_git_env,
        )

        emit_auto_config_log("", replace=True)
        emit_auto_config_log("Preparing repository checkout for temporary analysis chat...\n")
        emit_auto_config_log(f"Repository URL: {normalized_repo_url}\n")
        emit_auto_config_log(f"Requested branch: {requested_branch or 'auto-detect'}\n")
        emit_auto_config_log(f"Analysis agent: {resolved_agent_type}\n")
        emit_auto_config_log(
            f"Analysis model: {server_module._auto_config_analysis_model(resolved_agent_type, normalized_agent_args)}\n"
        )

        if self._state._is_auto_config_request_cancelled(normalized_request_id):
            raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR)

        try:
            with tempfile.TemporaryDirectory(prefix="agent-hub-auto-config-", dir=str(self._state.data_dir)) as temp_dir:
                workspace = Path(temp_dir) / "repo"
                env_candidates: list[dict[str, str]] = [authenticated_git_env]
                if git_env:
                    env_candidates.append(sanitized_git_env)

                def run_clone(cmd: list[str]) -> subprocess.CompletedProcess:
                    last_result = subprocess.CompletedProcess(cmd, 1, "", "")
                    for env_candidate in env_candidates:
                        if workspace.exists():
                            self._state._delete_path(workspace)
                        emit_auto_config_log(f"\n$ {' '.join(cmd)}\n")
                        result = server_module._run(cmd, capture=True, check=False, env=env_candidate)
                        command_output = ((result.stdout or "") + (result.stderr or "")).strip()
                        if command_output:
                            emit_auto_config_log(f"{command_output}\n")
                        elif result.returncode != 0:
                            emit_auto_config_log(f"Command exited with code {result.returncode}.\n")
                        if result.returncode == 0:
                            return result
                        last_result = result
                    return last_result

                clone_cmd_with_branch = [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    resolved_branch,
                    normalized_repo_url,
                    str(workspace),
                ]
                clone_result = run_clone(clone_cmd_with_branch)
                if clone_result.returncode != 0:
                    if requested_branch:
                        detail = ((clone_result.stdout or "") + (clone_result.stderr or "")).strip()
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Unable to clone repository branch '{requested_branch}'. "
                                f"{detail or 'git clone failed.'}"
                            ),
                        )

                    clone_cmd_default = ["git", "clone", "--depth", "1", normalized_repo_url, str(workspace)]
                    clone_result = run_clone(clone_cmd_default)
                    if clone_result.returncode != 0:
                        detail = ((clone_result.stdout or "") + (clone_result.stderr or "")).strip()
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unable to clone repository for auto-configure. {detail or 'git clone failed.'}",
                        )

                    head_result = server_module._run_for_repo(
                        ["rev-parse", "--abbrev-ref", "HEAD"],
                        workspace,
                        capture=True,
                        check=False,
                        env=sanitized_git_env,
                    )
                    if head_result.returncode == 0 and head_result.stdout.strip():
                        resolved_branch = head_result.stdout.strip()

                emit_auto_config_log("\nRepository checkout complete. Starting temporary analysis chat...\n")
                if self._state._is_auto_config_request_cancelled(normalized_request_id):
                    raise HTTPException(status_code=409, detail=server_module.AUTO_CONFIG_CANCELLED_ERROR)

                emit_auto_config_log("Running temporary analysis chat...\n")
                chat_result = self._state._run_temporary_auto_config_chat(
                    workspace,
                    normalized_repo_url,
                    resolved_branch,
                    agent_type=resolved_agent_type,
                    agent_args=normalized_agent_args,
                    on_output=emit_auto_config_log if normalized_request_id else None,
                    request_id=normalized_request_id,
                )
                container_workspace = server_module._container_workspace_path_for_project(
                    server_module._extract_repo_name(normalized_repo_url) or "auto-config"
                )
                recommendation = self._state._normalize_auto_config_recommendation(
                    chat_result.get("payload") or {},
                    workspace,
                    project_container_workspace=container_workspace,
                )
                recommendation = self._state._apply_auto_config_repository_hints(recommendation, workspace)
                recommendation = self._state._normalize_auto_config_recommendation(
                    recommendation,
                    workspace,
                    project_container_workspace=container_workspace,
                )
                emit_auto_config_log("Auto-config recommendation discovery completed.\n")
        except HTTPException as exc:
            detail = str(exc.detail or f"HTTP {exc.status_code}")
            emit_auto_config_log(f"\nAuto-config failed: {detail}\n")
            raise
        finally:
            self._state._clear_auto_config_request(normalized_request_id)

        recommendation["default_branch"] = resolved_branch
        emit_auto_config_log("\nAuto-config completed successfully.\n")
        return recommendation

    def cancel_auto_configure_project(self, *, request_id: Any) -> dict[str, Any]:
        return self._state.cancel_auto_configure_project(request_id=request_id)


__all__ = ["AutoConfigService"]
