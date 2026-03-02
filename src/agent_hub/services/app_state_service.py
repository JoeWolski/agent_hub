from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _runtime_symbols() -> Any:
    return importlib.import_module("agent_hub.server_hubstate_runtime_mixin")


class AppStateService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def state_payload(self) -> dict[str, Any]:
        runtime = _runtime_symbols()
        state_obj = self._state
        state = state_obj.load()
        project_map: dict[str, dict[str, Any]] = {}
        should_save = False
        for pid, project in state["projects"].items():
            project_copy = dict(project)
            normalized_base_mode = runtime._normalize_base_image_mode(project_copy.get("base_image_mode"))
            normalized_base_value = runtime._normalize_base_image_value(
                normalized_base_mode,
                project_copy.get("base_image_value"),
            )
            project_copy["base_image_mode"] = normalized_base_mode
            project_copy["base_image_value"] = normalized_base_value
            project_copy["default_ro_mounts"] = list(project_copy.get("default_ro_mounts") or [])
            project_copy["default_rw_mounts"] = list(project_copy.get("default_rw_mounts") or [])
            project_copy["default_env_vars"] = list(project_copy.get("default_env_vars") or [])
            project_copy["setup_snapshot_image"] = str(project_copy.get("setup_snapshot_image") or "")
            project_copy["build_status"] = str(project_copy.get("build_status") or "pending")
            project_copy["build_error"] = str(project_copy.get("build_error") or "")
            project_copy["build_started_at"] = str(project_copy.get("build_started_at") or "")
            project_copy["build_finished_at"] = str(project_copy.get("build_finished_at") or "")
            normalized_binding = runtime._normalize_project_credential_binding(project_copy.get("credential_binding"))
            project_copy["credential_binding"] = normalized_binding
            if state["projects"].get(pid, {}).get("base_image_mode") != normalized_base_mode:
                state["projects"][pid]["base_image_mode"] = normalized_base_mode
                should_save = True
            if str(state["projects"].get(pid, {}).get("base_image_value") or "").strip() != normalized_base_value:
                state["projects"][pid]["base_image_value"] = normalized_base_value
                should_save = True
            if state["projects"].get(pid, {}).get("credential_binding") != normalized_binding:
                state["projects"][pid]["credential_binding"] = normalized_binding
                should_save = True
            log_path = state_obj.project_build_log(pid)
            try:
                project_copy["has_build_log"] = log_path.exists() and log_path.stat().st_size > 0
            except OSError:
                project_copy["has_build_log"] = False
            project_map[pid] = project_copy
        chats = []
        for chat_id, chat in list(state["chats"].items()):
            chat_copy = dict(chat)
            pid = chat_copy.get("pid")
            chat_copy["ro_mounts"] = list(chat_copy.get("ro_mounts") or [])
            chat_copy["rw_mounts"] = list(chat_copy.get("rw_mounts") or [])
            chat_copy["env_vars"] = list(chat_copy.get("env_vars") or [])
            chat_copy["agent_type"] = runtime._normalize_state_chat_agent_type(
                chat_copy.get("agent_type"),
                chat_id=str(chat_id),
            )
            chat_copy["setup_snapshot_image"] = str(chat_copy.get("setup_snapshot_image") or "")
            cleaned_artifacts = runtime._normalize_chat_artifacts(chat_copy.get("artifacts"))
            if chat_id in state["chats"] and cleaned_artifacts != runtime._normalize_chat_artifacts(
                state["chats"][chat_id].get("artifacts")
            ):
                state["chats"][chat_id]["artifacts"] = cleaned_artifacts
                should_save = True
            current_ids_raw = chat_copy.get("artifact_current_ids")
            if isinstance(current_ids_raw, list):
                cleaned_current_artifact_ids = runtime._normalize_chat_current_artifact_ids(
                    current_ids_raw,
                    cleaned_artifacts,
                )
            else:
                cleaned_current_artifact_ids = [
                    str(artifact.get("id") or "")
                    for artifact in cleaned_artifacts
                    if str(artifact.get("id") or "")
                ]
            if chat_id in state["chats"]:
                state_current_ids_raw = state["chats"][chat_id].get("artifact_current_ids")
                if isinstance(state_current_ids_raw, list):
                    state_current_artifact_ids = runtime._normalize_chat_current_artifact_ids(
                        state_current_ids_raw,
                        cleaned_artifacts,
                    )
                else:
                    state_current_artifact_ids = [
                        str(artifact.get("id") or "")
                        for artifact in cleaned_artifacts
                        if str(artifact.get("id") or "")
                    ]
                if cleaned_current_artifact_ids != state_current_artifact_ids:
                    state["chats"][chat_id]["artifact_current_ids"] = cleaned_current_artifact_ids
                    should_save = True
            cleaned_artifact_prompt_history = runtime._normalize_chat_artifact_prompt_history(
                chat_copy.get("artifact_prompt_history")
            )
            if chat_id in state["chats"] and cleaned_artifact_prompt_history != runtime._normalize_chat_artifact_prompt_history(
                state["chats"][chat_id].get("artifact_prompt_history")
            ):
                state["chats"][chat_id]["artifact_prompt_history"] = cleaned_artifact_prompt_history
                should_save = True
            project_for_chat = project_map.get(chat_copy["project_id"], {})
            project_name = str(project_for_chat.get("name") or chat_copy["project_id"] or "project")
            chat_copy["artifacts"] = [
                state_obj._chat_artifact_public_payload(chat_id, artifact) for artifact in reversed(cleaned_artifacts)
            ]
            chat_copy["artifact_current_ids"] = cleaned_current_artifact_ids
            chat_copy["artifact_prompt_history"] = [
                state_obj._chat_artifact_history_public_payload(chat_id, entry)
                for entry in reversed(cleaned_artifact_prompt_history)
            ]
            chat_copy["ready_ack_guid"] = str(chat_copy.get("ready_ack_guid") or "").strip()
            chat_copy["ready_ack_stage"] = runtime._normalize_ready_ack_stage(chat_copy.get("ready_ack_stage"))
            chat_copy["ready_ack_at"] = str(chat_copy.get("ready_ack_at") or "")
            ready_ack_meta = chat_copy.get("ready_ack_meta")
            chat_copy["ready_ack_meta"] = ready_ack_meta if isinstance(ready_ack_meta, dict) else {}
            chat_copy.pop("artifact_publish_token_hash", None)
            chat_copy.pop("artifact_publish_token_issued_at", None)
            chat_copy.pop("agent_tools_token_hash", None)
            chat_copy.pop("agent_tools_token_issued_at", None)
            chat_copy["create_request_id"] = runtime._compact_whitespace(str(chat_copy.get("create_request_id") or "")).strip()
            running = runtime._is_process_running(pid)
            normalized_status = runtime._normalize_chat_status(chat_copy.get("status"))
            if running:
                if normalized_status != runtime.CHAT_STATUS_RUNNING and chat_id in state["chats"]:
                    state_obj._transition_chat_status(
                        chat_id,
                        state["chats"][chat_id],
                        runtime.CHAT_STATUS_RUNNING,
                        "chat_process_running_during_state_refresh",
                    )
                    should_save = True
                    persisted_chat = state["chats"][chat_id]
                    chat_copy["status"] = persisted_chat.get("status")
                    chat_copy["status_reason"] = persisted_chat.get("status_reason")
                    chat_copy["last_status_transition_at"] = persisted_chat.get("last_status_transition_at")
                    chat_copy["updated_at"] = persisted_chat.get("updated_at")
                chat_copy["status"] = runtime.CHAT_STATUS_RUNNING
            else:
                state_obj._close_runtime(chat_id)
                was_running = normalized_status in {
                    runtime.CHAT_STATUS_RUNNING,
                    runtime.CHAT_STATUS_STARTING,
                } or isinstance(pid, int)
                if was_running and chat_id in state["chats"]:
                    persisted_chat = state["chats"][chat_id]
                    state_obj._transition_chat_status(
                        chat_id,
                        persisted_chat,
                        runtime.CHAT_STATUS_FAILED,
                        "chat_process_not_running_during_state_refresh",
                    )
                    if not str(persisted_chat.get("start_error") or "").strip():
                        persisted_chat["start_error"] = "Chat process exited unexpectedly."
                    persisted_chat["pid"] = None
                    persisted_chat["artifact_publish_token_hash"] = ""
                    persisted_chat["artifact_publish_token_issued_at"] = ""
                    persisted_chat["agent_tools_token_hash"] = ""
                    persisted_chat["agent_tools_token_issued_at"] = ""
                    persisted_chat["last_exit_code"] = runtime._normalize_optional_int(persisted_chat.get("last_exit_code"))
                    if not str(persisted_chat.get("last_exit_at") or "").strip():
                        persisted_chat["last_exit_at"] = runtime._iso_now()
                    persisted_chat["stop_requested_at"] = ""
                    state["chats"][chat_id] = persisted_chat
                    chat_copy["status"] = persisted_chat.get("status")
                    chat_copy["status_reason"] = persisted_chat.get("status_reason")
                    chat_copy["last_status_transition_at"] = persisted_chat.get("last_status_transition_at")
                    chat_copy["updated_at"] = persisted_chat.get("updated_at")
                    chat_copy["start_error"] = persisted_chat.get("start_error")
                    chat_copy["last_exit_code"] = persisted_chat.get("last_exit_code")
                    chat_copy["last_exit_at"] = persisted_chat.get("last_exit_at")
                    chat_copy["stop_requested_at"] = persisted_chat.get("stop_requested_at")
                    chat_copy["pid"] = None
                    should_save = True
                else:
                    chat_copy["status"] = normalized_status
                    if chat_copy.get("pid") is not None:
                        chat_copy["pid"] = None
                        if chat_id in state["chats"]:
                            state["chats"][chat_id]["pid"] = None
                            state["chats"][chat_id]["updated_at"] = runtime._iso_now()
                            should_save = True
            chat_copy["is_running"] = running
            chat_copy["container_workspace"] = str(chat_copy.get("container_workspace") or "") or runtime._container_workspace_path_for_project(
                project_name
            )
            chat_copy["project_name"] = project_name
            is_outdated, outdated_reason = state_obj._chat_container_outdated_state(
                chat=chat_copy,
                project=project_for_chat,
                is_running=running,
            )
            chat_copy["container_outdated"] = is_outdated
            chat_copy["container_outdated_reason"] = outdated_reason
            subtitle = runtime._chat_subtitle_from_log(state_obj.chat_log(chat_id))
            cached_title = runtime._truncate_title(str(chat_copy.get("title_cached") or ""), runtime.CHAT_TITLE_MAX_CHARS)
            if cached_title and runtime._looks_like_terminal_control_payload(cached_title):
                cached_title = ""
                if chat_id in state["chats"]:
                    state["chats"][chat_id]["title_cached"] = ""
                    state["chats"][chat_id]["title_source"] = ""
                    state["chats"][chat_id]["title_prompt_fingerprint"] = ""
                    should_save = True
            history_raw = chat_copy.get("title_user_prompts")
            if isinstance(history_raw, list):
                cleaned_history = [
                    str(item)
                    for item in history_raw
                    if str(item).strip() and not runtime._looks_like_terminal_control_payload(str(item))
                ]
                if chat_id in state["chats"] and cleaned_history != list(history_raw):
                    state["chats"][chat_id]["title_user_prompts"] = cleaned_history
                    should_save = True
            title_status = str(chat_copy.get("title_status") or "idle").lower()
            if title_status == "pending":
                pending_history = chat_copy.get("title_user_prompts")
                if isinstance(pending_history, list):
                    normalized_prompts = runtime._normalize_chat_prompt_history(
                        [str(item) for item in pending_history if str(item).strip()]
                    )
                    if normalized_prompts:
                        state_obj._schedule_chat_title_generation(chat_id)
            chat_copy["display_name"] = cached_title or runtime._chat_display_name(chat_copy.get("name"))
            title_error = runtime._compact_whitespace(str(chat_copy.get("title_error") or ""))
            if not subtitle and title_error:
                subtitle = runtime._short_summary(
                    f"Title generation error: {title_error}",
                    max_words=20,
                    max_chars=runtime.CHAT_SUBTITLE_MAX_CHARS,
                )
            chat_copy["display_subtitle"] = subtitle
            chats.append(chat_copy)

        if should_save:
            state_obj.save(state, reason="state_payload_reconcile")

        state["chats"] = chats
        state["projects"] = list(project_map.values())
        state["settings"] = state_obj.settings_service.settings_payload(state)
        return state

    def settings_payload(self) -> dict[str, Any]:
        return self._state.settings_payload()

    def update_settings(self, update: dict[str, Any]) -> dict[str, Any]:
        return self._state.update_settings(update)

    def default_chat_agent_type(self) -> str:
        return self._state.default_chat_agent_type()

    def agent_capabilities_payload(self) -> dict[str, Any]:
        return self._state.agent_capabilities_payload()

    def start_agent_capabilities_discovery(self) -> dict[str, Any]:
        return self._state.start_agent_capabilities_discovery()
