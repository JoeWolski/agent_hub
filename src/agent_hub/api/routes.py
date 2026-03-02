from __future__ import annotations

import asyncio
import json
import logging
import queue
import urllib.parse
from pathlib import Path
from typing import Any, Callable

import click
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


def register_hub_routes(
    app: FastAPI,
    *,
    state: Any,
    frontend_dist: Path,
    frontend_index: Path,
    logger: logging.Logger,
    event_type_snapshot: str,
    agent_type_codex: str,
    iso_now: Callable[[], str],
    frontend_not_built_page: Callable[[], str],
    coerce_bool: Callable[..., bool],
    github_app_setup_callback_page: Callable[..., str],
    normalize_openai_account_login_method: Callable[..., str],
    openai_callback_request_context_from_request: Callable[[Request], dict[str, Any]],
    normalize_chat_agent_type: Callable[..., str],
    normalize_base_image_mode: Callable[..., str],
    normalize_project_credential_binding: Callable[..., Any],
    parse_mounts: Callable[..., Any],
    empty_list: Callable[..., list[Any]],
    parse_env_vars: Callable[..., Any],
    compact_whitespace: Callable[[str], str],
    parse_artifact_request_payload: Callable[..., Any],
    cleanup_uploaded_artifact_paths: Callable[[list[Path]], None],
) -> None:
    @app.get("/", response_class=HTMLResponse)
    def index():
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return HTMLResponse(frontend_not_built_page(), status_code=503)

    @app.websocket("/api/events")
    async def ws_events(websocket: WebSocket) -> None:
        listener = state.event_service.attach_events()
        await websocket.accept()
        logger.debug("Hub events websocket connected.")
        snapshot_event = {
            "type": event_type_snapshot,
            "payload": state.event_service.events_snapshot(),
            "sent_at": iso_now(),
        }
        await websocket.send_text(json.dumps(snapshot_event))

        async def stream_events() -> None:
            while True:
                try:
                    event = await asyncio.to_thread(listener.get, True, 0.5)
                except queue.Empty:
                    continue
                if event is None:
                    break
                await websocket.send_text(json.dumps(event))

        async def consume_input() -> None:
            while True:
                try:
                    message = await websocket.receive_text()
                except WebSocketDisconnect:
                    return
                if not message:
                    continue
                payload: Any = None
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and str(payload.get("type") or "") == "ping":
                    await websocket.send_text(
                        json.dumps({"type": "pong", "payload": {"at": iso_now()}, "sent_at": iso_now()})
                    )

        sender = asyncio.create_task(stream_events())
        receiver = asyncio.create_task(consume_input())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            state.event_service.queue_put(listener, None)
            state.event_service.detach_events(listener)
            if not sender.done():
                sender.cancel()
            if not receiver.done():
                receiver.cancel()
            logger.debug("Hub events websocket disconnected.")

    @app.get("/api/state")
    def api_state() -> dict[str, Any]:
        return state.app_state_service.state_payload()

    @app.get("/api/settings")
    def api_settings() -> dict[str, Any]:
        return {"settings": state.app_state_service.settings_payload()}

    @app.get("/api/runtime-flags")
    def api_runtime_flags() -> dict[str, Any]:
        return state.runtime_service.runtime_flags_payload()

    @app.patch("/api/settings")
    async def api_update_settings(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        updated = state.app_state_service.update_settings(payload)
        return {"settings": updated}

    @app.get("/api/agent-capabilities")
    def api_agent_capabilities() -> dict[str, Any]:
        return state.app_state_service.agent_capabilities_payload()

    @app.post("/api/agent-capabilities/discover")
    def api_discover_agent_capabilities() -> dict[str, Any]:
        return state.app_state_service.start_agent_capabilities_discovery()

    @app.get("/api/settings/auth")
    def api_auth_settings() -> dict[str, Any]:
        return state.auth_service.auth_settings_payload()

    @app.post("/api/settings/auth/openai/connect")
    async def api_connect_openai(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        verify = coerce_bool(payload.get("verify"), default=True, field_name="verify")
        return state.auth_service.connect_openai(payload.get("api_key"), verify=verify)

    @app.post("/api/settings/auth/openai/disconnect")
    def api_disconnect_openai() -> dict[str, Any]:
        return state.auth_service.disconnect_openai()

    @app.post("/api/settings/auth/github-app/connect")
    async def api_connect_github_app(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.auth_service.connect_github_app(payload.get("installation_id"))

    @app.post("/api/settings/auth/github-app/setup/start")
    async def api_start_github_app_setup(request: Request) -> dict[str, Any]:
        origin = f"{request.url.scheme}://{request.url.netloc}"
        raw_body = await request.body()
        if raw_body:
            try:
                payload = json.loads(raw_body.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
            if payload is not None and not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Invalid JSON payload.")
            if isinstance(payload, dict) and "origin" in payload:
                origin = str(payload.get("origin") or "").strip()
        return state.auth_service.start_github_app_setup(origin=origin)

    @app.get("/api/settings/auth/github-app/setup/session")
    def api_github_app_setup_session() -> dict[str, Any]:
        return state.auth_service.github_app_setup_session_payload()

    @app.get("/api/settings/auth/github-app/setup/callback", response_class=HTMLResponse)
    def api_github_app_setup_callback(request: Request) -> HTMLResponse:
        denied_error = str(request.query_params.get("error") or "").strip()
        state_value = str(request.query_params.get("state") or "").strip()
        if denied_error:
            message = str(request.query_params.get("error_description") or denied_error).strip()
            state.auth_service.fail_github_app_setup(message=message or denied_error, state_value=state_value)
            return HTMLResponse(
                github_app_setup_callback_page(
                    success=False,
                    message=message or "GitHub app setup was cancelled.",
                ),
                status_code=400,
            )

        code = str(request.query_params.get("code") or "").strip()
        try:
            payload = state.auth_service.complete_github_app_setup(code=code, state_value=state_value)
            app_slug = str(payload.get("app_slug") or "")
            return HTMLResponse(
                github_app_setup_callback_page(
                    success=True,
                    message="GitHub App setup completed. Return to Agent Hub and select the installation to connect.",
                    app_slug=app_slug,
                )
            )
        except HTTPException as exc:
            return HTMLResponse(
                github_app_setup_callback_page(
                    success=False,
                    message=str(exc.detail or "GitHub app setup failed."),
                ),
                status_code=int(exc.status_code or 400),
            )

    @app.post("/api/settings/auth/github-app/disconnect")
    def api_disconnect_github_app() -> dict[str, Any]:
        return state.auth_service.disconnect_github_app()

    @app.get("/api/settings/auth/github-app/installations")
    def api_list_github_installations() -> dict[str, Any]:
        return state.auth_service.list_github_app_installations()

    @app.post("/api/settings/auth/github-tokens/connect")
    async def api_connect_github_token(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.auth_service.connect_github_personal_access_token(
            payload.get("personal_access_token"),
            host=payload.get("host"),
        )

    @app.delete("/api/settings/auth/github-tokens/{token_id}")
    def api_disconnect_github_personal_access_token(token_id: str) -> dict[str, Any]:
        return state.auth_service.disconnect_github_personal_access_token(token_id)

    @app.post("/api/settings/auth/github-tokens/disconnect")
    def api_disconnect_github_personal_access_tokens() -> dict[str, Any]:
        return state.auth_service.disconnect_github_personal_access_tokens()

    @app.post("/api/settings/auth/gitlab-tokens/connect")
    async def api_connect_gitlab_token(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.auth_service.connect_gitlab_personal_access_token(
            payload.get("personal_access_token"),
            host=payload.get("host"),
        )

    @app.delete("/api/settings/auth/gitlab-tokens/{token_id}")
    def api_disconnect_gitlab_personal_access_token(token_id: str) -> dict[str, Any]:
        return state.auth_service.disconnect_gitlab_personal_access_token(token_id)

    @app.post("/api/settings/auth/gitlab-tokens/disconnect")
    def api_disconnect_gitlab_personal_access_tokens() -> dict[str, Any]:
        return state.auth_service.disconnect_gitlab_personal_access_tokens()

    @app.post("/api/settings/auth/openai/title-test")
    async def api_test_openai_chat_title_generation(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.auth_service.test_openai_chat_title_generation(payload.get("prompt"))

    @app.post("/api/settings/auth/openai/account/disconnect")
    def api_disconnect_openai_account() -> dict[str, Any]:
        return state.auth_service.disconnect_openai_account()

    @app.get("/api/settings/auth/openai/account/session")
    def api_openai_account_session() -> dict[str, Any]:
        return state.auth_service.openai_account_session_payload()

    @app.post("/api/settings/auth/openai/account/start")
    async def api_start_openai_account_login(request: Request) -> dict[str, Any]:
        method = "browser_callback"
        raw_body = await request.body()
        if raw_body:
            try:
                payload = json.loads(raw_body.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
            if payload is not None and not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Invalid JSON payload.")
            if isinstance(payload, dict):
                method = normalize_openai_account_login_method(payload.get("method"))
        return state.auth_service.start_openai_account_login(method=method)

    @app.post("/api/settings/auth/openai/account/cancel")
    def api_cancel_openai_account_login() -> dict[str, Any]:
        return state.auth_service.cancel_openai_account_login()

    @app.get("/api/settings/auth/openai/account/callback")
    def api_openai_account_callback(request: Request) -> dict[str, Any]:
        callback_path = str(request.query_params.get("callback_path") or "")
        query_items = [(key, value) for key, value in request.query_params.multi_items() if key != "callback_path"]
        request_client_host = request.client.host if request.client is not None else ""
        request_context = openai_callback_request_context_from_request(request)
        forwarded = state.lifecycle_service.forward_openai_account_callback(
            urllib.parse.urlencode(query_items, doseq=True),
            path=callback_path,
            request_host=request_client_host,
            request_context=request_context,
        )
        payload = state.auth_service.openai_account_session_payload()
        payload["callback"] = forwarded
        return payload

    @app.post("/api/projects/auto-configure")
    async def api_auto_configure_project(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        agent_args = payload.get("agent_args")
        if agent_args is None:
            agent_args = []
        if not isinstance(agent_args, list):
            raise HTTPException(status_code=400, detail="agent_args must be an array.")
        agent_type = (
            normalize_chat_agent_type(payload.get("agent_type"), strict=True)
            if "agent_type" in payload
            else agent_type_codex
        )
        recommendation = await asyncio.to_thread(
            state.auto_config_service.auto_configure_project,
            repo_url=payload.get("repo_url"),
            default_branch=payload.get("default_branch"),
            request_id=payload.get("request_id"),
            agent_type=agent_type,
            agent_args=[str(arg) for arg in agent_args if str(arg).strip()],
        )
        return {"recommendation": recommendation}

    @app.post("/api/projects/auto-configure/cancel")
    async def api_cancel_auto_configure_project(request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.auto_config_service.cancel_auto_configure_project(
            request_id=payload.get("request_id"),
        )

    @app.post("/api/projects")
    async def api_create_project(request: Request) -> dict[str, Any]:
        payload = await request.json()
        repo_url = str(payload.get("repo_url", "")).strip()
        name = payload.get("name")
        if name is not None:
            name = str(name).strip() or None
        branch = payload.get("default_branch")
        setup_script = payload.get("setup_script")
        base_image_mode = normalize_base_image_mode(payload.get("base_image_mode"))
        base_image_value = str(payload.get("base_image_value") or "").strip()
        default_ro_mounts = parse_mounts(empty_list(payload.get("default_ro_mounts")), "default read-only mount")
        default_rw_mounts = parse_mounts(empty_list(payload.get("default_rw_mounts")), "default read-write mount")
        default_env_vars = parse_env_vars(empty_list(payload.get("default_env_vars")))
        credential_binding = normalize_project_credential_binding(payload.get("credential_binding"), strict=True)
        if setup_script is not None:
            setup_script = str(setup_script).strip()
        if isinstance(branch, str):
            branch = branch.strip() or None
        project = await asyncio.to_thread(
            state.project_service.create_project,
            repo_url=repo_url,
            name=name,
            default_branch=branch,
            setup_script=setup_script,
            base_image_mode=base_image_mode,
            base_image_value=base_image_value,
            default_ro_mounts=default_ro_mounts,
            default_rw_mounts=default_rw_mounts,
            default_env_vars=default_env_vars,
            credential_binding=credential_binding,
        )
        return {
            "project": project
        }

    @app.patch("/api/projects/{project_id}")
    async def api_update_project(project_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        update: dict[str, Any] = {}
        if "setup_script" in payload:
            script = payload.get("setup_script")
            update["setup_script"] = str(script).strip() if script is not None else ""
        if "name" in payload:
            name = payload.get("name")
            update["name"] = str(name).strip() if name is not None else ""
        if "default_branch" in payload:
            branch = payload.get("default_branch")
            update["default_branch"] = str(branch).strip() if branch is not None else ""
        if "base_image_mode" in payload:
            update["base_image_mode"] = normalize_base_image_mode(payload.get("base_image_mode"))
        if "base_image_value" in payload:
            value = payload.get("base_image_value")
            update["base_image_value"] = str(value).strip() if value is not None else ""
        if "default_ro_mounts" in payload:
            update["default_ro_mounts"] = parse_mounts(
                empty_list(payload.get("default_ro_mounts")),
                "default read-only mount",
            )
        if "default_rw_mounts" in payload:
            update["default_rw_mounts"] = parse_mounts(
                empty_list(payload.get("default_rw_mounts")),
                "default read-write mount",
            )
        if "default_env_vars" in payload:
            update["default_env_vars"] = parse_env_vars(empty_list(payload.get("default_env_vars")))
        if "credential_binding" in payload:
            update["credential_binding"] = normalize_project_credential_binding(payload.get("credential_binding"), strict=True)
        if not update:
            raise HTTPException(status_code=400, detail="No patch values provided.")
        project = await asyncio.to_thread(state.project_service.update_project, project_id, update)
        return {"project": project}

    @app.get("/api/projects/{project_id}/credential-binding")
    def api_project_credential_binding(project_id: str) -> dict[str, Any]:
        return state.project_service.credential_binding_payload(project_id)

    @app.post("/api/projects/{project_id}/credential-binding")
    async def api_project_credential_binding_update(project_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.project_service.attach_project_credentials(
            project_id=project_id,
            mode=payload.get("mode"),
            credential_ids=payload.get("credential_ids"),
            source="settings_api",
        )

    @app.delete("/api/projects/{project_id}")
    def api_delete_project(project_id: str) -> None:
        state.project_service.delete_project(project_id)

    @app.post("/api/projects/{project_id}/build/cancel")
    def api_cancel_project_build(project_id: str) -> dict[str, Any]:
        return state.project_service.cancel_project_build(project_id)

    @app.get("/api/projects/{project_id}/build-logs", response_class=PlainTextResponse)
    def api_project_build_logs(project_id: str) -> str:
        return state.project_service.project_build_logs(project_id)

    @app.get("/api/projects/{project_id}/launch-profile")
    def api_project_launch_profile(project_id: str) -> dict[str, Any]:
        return {"launch_profile": state.project_service.project_launch_profile(project_id)}

    @app.post("/api/projects/{project_id}/chats/start")
    async def api_start_new_chat_for_project(project_id: str, request: Request) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        body = await request.body()
        if body:
            try:
                parsed_payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
            if not isinstance(parsed_payload, dict):
                raise HTTPException(status_code=400, detail="Request body must be an object.")
            payload = parsed_payload

        if "codex_args" in payload:
            raise HTTPException(status_code=400, detail="codex_args is no longer supported; use agent_args.")
        if "agent_args" not in payload:
            raise HTTPException(status_code=400, detail="agent_args is required and must be an array.")
        agent_args = payload.get("agent_args")
        if not isinstance(agent_args, list):
            raise HTTPException(status_code=400, detail="agent_args must be an array.")
        request_id_raw = payload.get("request_id")
        request_id = compact_whitespace(str(request_id_raw or "")).strip()
        agent_type = (
            normalize_chat_agent_type(payload.get("agent_type"), strict=True)
            if "agent_type" in payload
            else state.app_state_service.default_chat_agent_type()
        )
        start_kwargs: dict[str, Any] = {
            "agent_args": [str(arg) for arg in agent_args],
            "agent_type": agent_type,
        }
        if request_id:
            start_kwargs["request_id"] = request_id
        chat = await asyncio.to_thread(
            state.project_service.create_and_start_chat,
            project_id,
            **start_kwargs,
        )
        return {
            "chat": chat
        }

    @app.post("/api/chats")
    async def api_create_chat(request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        project_id = str(payload.get("project_id", "")).strip()
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")

        profile = payload.get("profile")
        if profile is not None:
            profile = str(profile).strip()

        ro_mounts = parse_mounts(empty_list(payload.get("ro_mounts")), "read-only mount")
        rw_mounts = parse_mounts(empty_list(payload.get("rw_mounts")), "read-write mount")
        env_vars = parse_env_vars(empty_list(payload.get("env_vars")))
        if "codex_args" in payload:
            raise HTTPException(status_code=400, detail="codex_args is no longer supported; use agent_args.")
        if "agent_args" not in payload:
            raise HTTPException(status_code=400, detail="agent_args is required and must be an array.")
        agent_args = payload.get("agent_args")
        if not isinstance(agent_args, list):
            raise HTTPException(status_code=400, detail="agent_args must be an array.")
        agent_type = (
            normalize_chat_agent_type(payload.get("agent_type"), strict=True)
            if "agent_type" in payload
            else state.app_state_service.default_chat_agent_type()
        )
        chat = await asyncio.to_thread(
            state.chat_service.create_chat,
            project_id=project_id,
            profile=profile,
            ro_mounts=ro_mounts,
            rw_mounts=rw_mounts,
            env_vars=env_vars,
            agent_args=[str(arg) for arg in agent_args],
            agent_type=agent_type,
        )
        return {
            "chat": chat
        }

    @app.post("/api/chats/{chat_id}/start")
    def api_start_chat(chat_id: str) -> dict[str, Any]:
        return {"chat": state.chat_service.start_chat(chat_id)}

    @app.get("/api/chats/{chat_id}/launch-profile")
    def api_chat_launch_profile(chat_id: str, resume: bool = False) -> dict[str, Any]:
        return {"launch_profile": state.chat_service.chat_launch_profile(chat_id, resume=resume)}

    @app.post("/api/chats/{chat_id}/refresh-container")
    def api_refresh_chat_container(chat_id: str) -> dict[str, Any]:
        return {"chat": state.chat_service.refresh_chat_container(chat_id)}

    @app.post("/api/chats/{chat_id}/close")
    def api_close_chat(chat_id: str) -> dict[str, Any]:
        return {"chat": state.chat_service.close_chat(chat_id)}

    @app.patch("/api/chats/{chat_id}")
    async def api_patch_chat(chat_id: str, request: Request) -> dict[str, Any]:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON payload.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        update: dict[str, Any] = {}
        if "profile" in payload:
            update["profile"] = str(payload.get("profile") or "").strip()
        if "ro_mounts" in payload:
            update["ro_mounts"] = parse_mounts(empty_list(payload.get("ro_mounts")), "read-only mount")
        if "rw_mounts" in payload:
            update["rw_mounts"] = parse_mounts(empty_list(payload.get("rw_mounts")), "read-write mount")
        if "env_vars" in payload:
            update["env_vars"] = parse_env_vars(empty_list(payload.get("env_vars")))
        if "codex_args" in payload:
            raise HTTPException(status_code=400, detail="codex_args is no longer supported; use agent_args.")
        if "agent_args" in payload:
            args = payload.get("agent_args")
            if not isinstance(args, list):
                raise HTTPException(status_code=400, detail="agent_args must be an array.")
            update["agent_args"] = [str(arg) for arg in args]
        if "agent_type" in payload:
            update["agent_type"] = normalize_chat_agent_type(payload.get("agent_type"), strict=True)
        if not update:
            raise HTTPException(status_code=400, detail="No patch values provided.")
        return {"chat": state.chat_service.update_chat(chat_id, update)}

    @app.delete("/api/chats/{chat_id}")
    def api_delete_chat(chat_id: str) -> None:
        state.chat_service.delete_chat(chat_id)

    @app.post("/api/chats/{chat_id}/title-prompt")
    async def api_chat_title_prompt(chat_id: str, request: Request) -> dict[str, Any]:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.chat_service.record_chat_title_prompt(chat_id, payload.get("prompt"))

    @app.get("/api/chats/{chat_id}/artifacts")
    def api_list_chat_artifacts(chat_id: str) -> dict[str, Any]:
        return {"artifacts": state.artifacts_service.list_chat_artifacts(chat_id)}

    @app.post("/api/chats/{chat_id}/artifacts/publish")
    async def api_publish_chat_artifact(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.artifacts_service.resolve_artifact_publish_token(request.headers)
        workspace = state.artifacts_service.require_chat_publish_workspace(chat_id=chat_id, token=token)
        payload, staged_paths = await parse_artifact_request_payload(
            request,
            context=f"/api/chats/{chat_id}/artifacts/publish",
            workspace=workspace,
        )
        try:
            artifact = state.artifacts_service.publish_chat_artifact(
                chat_id=chat_id,
                token=token,
                submitted_path=payload.get("path"),
                name=payload.get("name"),
            )
        except HTTPException as exc:
            logger.warning(
                "artifacts publish failed for chat_id=%s: %s",
                chat_id,
                exc.detail,
            )
            raise
        finally:
            cleanup_uploaded_artifact_paths(staged_paths)
        return {"artifact": artifact}

    @app.get("/api/chats/{chat_id}/artifacts/{artifact_id}/download")
    def api_download_chat_artifact(chat_id: str, artifact_id: str) -> FileResponse:
        artifact_path, filename, media_type = state.artifacts_service.resolve_chat_artifact_download(chat_id, artifact_id)
        return FileResponse(path=str(artifact_path), filename=filename, media_type=media_type)

    @app.get("/api/chats/{chat_id}/artifacts/{artifact_id}/preview")
    def api_preview_chat_artifact(chat_id: str, artifact_id: str) -> FileResponse:
        artifact_path, media_type = state.artifacts_service.resolve_chat_artifact_preview(chat_id, artifact_id)
        return FileResponse(path=str(artifact_path), media_type=media_type)

    @app.get("/api/chats/{chat_id}/agent-tools/credentials")
    def api_agent_tools_list_credentials(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        return state.credentials_service.list_chat_credentials(chat_id=chat_id, token=token)

    @app.post("/api/chats/{chat_id}/agent-tools/credentials/resolve")
    async def api_agent_tools_resolve_credentials(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.credentials_service.resolve_chat_credentials(
            chat_id=chat_id,
            token=token,
            mode=payload.get("mode"),
            credential_ids=payload.get("credential_ids"),
        )

    @app.post("/api/chats/{chat_id}/agent-tools/project-binding")
    async def api_agent_tools_attach_project_binding(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.credentials_service.attach_chat_project_credentials(
            chat_id=chat_id,
            token=token,
            mode=payload.get("mode"),
            credential_ids=payload.get("credential_ids"),
        )

    @app.post("/api/chats/{chat_id}/agent-tools/ack")
    async def api_agent_tools_ack_chat_ready(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        acknowledgement = state.credentials_service.acknowledge_chat_ready(
            chat_id=chat_id,
            token=token,
            guid=payload.get("guid"),
            stage=payload.get("stage"),
            meta=payload.get("meta"),
        )
        return {"ack": acknowledgement}

    @app.post("/api/chats/{chat_id}/agent-tools/artifacts/submit")
    async def api_agent_tools_submit_chat_artifact(chat_id: str, request: Request) -> dict[str, Any]:
        token = state.artifacts_service.resolve_agent_tools_token(request.headers)
        workspace = state.artifacts_service.require_chat_submit_workspace(chat_id=chat_id, token=token)
        payload, staged_paths = await parse_artifact_request_payload(
            request,
            context=f"/api/chats/{chat_id}/agent-tools/artifacts/submit",
            workspace=workspace,
        )
        try:
            artifact = state.artifacts_service.submit_chat_artifact(
                chat_id=chat_id,
                token=token,
                submitted_path=payload.get("path"),
                name=payload.get("name"),
            )
        except HTTPException as exc:
            logger.warning(
                "agent-tools artifact submit failed for chat_id=%s: %s",
                chat_id,
                exc.detail,
            )
            raise
        finally:
            cleanup_uploaded_artifact_paths(staged_paths)
        return {"artifact": artifact}

    @app.get("/api/agent-tools/sessions/{session_id}/credentials")
    def api_agent_tools_session_list_credentials(session_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        return state.credentials_service.list_session_credentials(session_id=session_id, token=token)

    @app.post("/api/agent-tools/sessions/{session_id}/credentials/resolve")
    async def api_agent_tools_session_resolve_credentials(session_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.credentials_service.resolve_session_credentials(
            session_id=session_id,
            token=token,
            mode=payload.get("mode"),
            credential_ids=payload.get("credential_ids"),
        )

    @app.post("/api/agent-tools/sessions/{session_id}/project-binding")
    async def api_agent_tools_session_attach_project_binding(session_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        return state.credentials_service.attach_session_project_credentials(
            session_id=session_id,
            token=token,
            mode=payload.get("mode"),
            credential_ids=payload.get("credential_ids"),
        )

    @app.post("/api/agent-tools/sessions/{session_id}/ack")
    async def api_agent_tools_ack_session_ready(session_id: str, request: Request) -> dict[str, Any]:
        token = state.credentials_service.resolve_token(request.headers)
        payload = await request.json()
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON payload.")
        acknowledgement = state.credentials_service.acknowledge_session_ready(
            session_id=session_id,
            token=token,
            guid=payload.get("guid"),
            stage=payload.get("stage"),
            meta=payload.get("meta"),
        )
        return {"ack": acknowledgement}

    @app.post("/api/agent-tools/sessions/{session_id}/artifacts/publish")
    async def api_publish_session_artifact(session_id: str, request: Request) -> dict[str, Any]:
        token = state.artifacts_service.resolve_artifact_publish_token(request.headers)
        workspace = state.artifacts_service.require_session_publish_workspace(session_id=session_id, token=token)
        payload, staged_paths = await parse_artifact_request_payload(
            request,
            context=f"/api/agent-tools/sessions/{session_id}/artifacts/publish",
            workspace=workspace,
        )
        try:
            artifact = state.artifacts_service.publish_session_artifact(
                session_id=session_id,
                token=token,
                submitted_path=payload.get("path"),
                name=payload.get("name"),
            )
        except HTTPException as exc:
            logger.warning(
                "session artifact publish failed for session_id=%s: %s",
                session_id,
                exc.detail,
            )
            raise
        finally:
            cleanup_uploaded_artifact_paths(staged_paths)
        return {"artifact": artifact}

    @app.post("/api/agent-tools/sessions/{session_id}/artifacts/submit")
    async def api_agent_tools_submit_session_artifact(session_id: str, request: Request) -> dict[str, Any]:
        token = state.artifacts_service.resolve_agent_tools_token(request.headers)
        workspace = state.artifacts_service.require_session_submit_workspace(session_id=session_id, token=token)
        payload, staged_paths = await parse_artifact_request_payload(
            request,
            context=f"/api/agent-tools/sessions/{session_id}/artifacts/submit",
            workspace=workspace,
        )
        try:
            artifact = state.artifacts_service.submit_session_artifact(
                session_id=session_id,
                token=token,
                submitted_path=payload.get("path"),
                name=payload.get("name"),
            )
        except HTTPException as exc:
            logger.warning(
                "session artifact submit failed for session_id=%s: %s",
                session_id,
                exc.detail,
            )
            raise
        finally:
            cleanup_uploaded_artifact_paths(staged_paths)
        return {"artifact": artifact}

    @app.get("/api/agent-tools/sessions/{session_id}/artifacts/{artifact_id}/download")
    def api_download_session_artifact(session_id: str, artifact_id: str) -> FileResponse:
        artifact_path, filename, media_type = state.artifacts_service.resolve_session_artifact_download(
            session_id,
            artifact_id,
        )
        return FileResponse(path=str(artifact_path), filename=filename, media_type=media_type)

    @app.get("/api/agent-tools/sessions/{session_id}/artifacts/{artifact_id}/preview")
    def api_preview_session_artifact(session_id: str, artifact_id: str) -> FileResponse:
        artifact_path, media_type = state.artifacts_service.resolve_session_artifact_preview(session_id, artifact_id)
        return FileResponse(path=str(artifact_path), media_type=media_type)

    @app.get("/api/chats/{chat_id}/logs", response_class=PlainTextResponse)
    def api_chat_logs(chat_id: str) -> str:
        return state.chat_service.chat_logs(chat_id)

    @app.websocket("/api/chats/{chat_id}/terminal")
    async def ws_chat_terminal(chat_id: str, websocket: WebSocket) -> None:
        chat = state.chat_service.chat(chat_id)
        if chat is None:
            await websocket.close(code=4404)
            return

        try:
            listener, backlog = state.chat_service.attach_terminal(chat_id)
        except HTTPException as exc:
            await websocket.close(code=4409, reason=str(exc.detail))
            return

        await websocket.accept()
        if backlog:
            try:
                await websocket.send_text(backlog)
            except WebSocketDisconnect:
                state.chat_service.queue_put(listener, None)
                state.chat_service.detach_terminal(chat_id, listener)
                return

        async def stream_output() -> None:
            while True:
                try:
                    chunk = await asyncio.to_thread(listener.get, True, 0.25)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                try:
                    await websocket.send_text(chunk)
                except WebSocketDisconnect:
                    break

        async def stream_input() -> None:
            while True:
                message = await websocket.receive_text()
                payload: Any = None
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    state.chat_service.write_terminal_input(chat_id, message)
                    continue

                if isinstance(payload, dict):
                    message_type = str(payload.get("type") or "")
                    if message_type == "resize":
                        state.chat_service.resize_terminal(chat_id, int(payload.get("cols") or 0), int(payload.get("rows") or 0))
                        continue
                    if message_type == "submit":
                        state.chat_service.submit_chat_input_buffer(chat_id)
                        continue
                    if message_type == "input":
                        state.chat_service.write_terminal_input(chat_id, str(payload.get("data") or ""))
                        continue

                state.chat_service.write_terminal_input(chat_id, message)

        sender = asyncio.create_task(stream_output())
        receiver = asyncio.create_task(stream_input())
        try:
            done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            state.chat_service.queue_put(listener, None)
            state.chat_service.detach_terminal(chat_id, listener)
            if not sender.done():
                sender.cancel()
            if not receiver.done():
                receiver.cancel()

    assets_dir = frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.on_event("shutdown")
    async def app_shutdown() -> None:
        try:
            summary = state.lifecycle_service.shutdown()
            if summary["closed_chats"] > 0:
                click.echo(
                    "Shutdown cleanup completed: "
                    f"stopped_chats={summary['stopped_chats']} "
                    f"closed_chats={summary['closed_chats']}"
                )
        except Exception as exc:  # pragma: no cover - defensive shutdown guard
            click.echo(f"Shutdown cleanup failed: {exc}", err=True)

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = frontend_dist / path
        if candidate.is_file():
            return FileResponse(candidate)
        if frontend_index.is_file():
            return FileResponse(frontend_index)
        return HTMLResponse(frontend_not_built_page(), status_code=503)
