from __future__ import annotations

from typing import Any

from agent_core.errors import RuntimeStateError, TypedAgentError

from .launch_profile_service import LaunchProfileService


class RuntimeService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def runtime_flags_payload(self) -> dict[str, Any]:
        return self._state.runtime_flags_payload()

    def start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]:
        from agent_hub import server_hubstate_runtime_mixin as runtime_mixin

        state = self._state.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat["project_id"])
        if project is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Parent project missing.")
        launch_profile_service = LaunchProfileService(state=self._state)

        if runtime_mixin._normalize_chat_status(chat.get("status")) == runtime_mixin.CHAT_STATUS_RUNNING and runtime_mixin._is_process_running(chat.get("pid")):
            raise runtime_mixin.HTTPException(status_code=409, detail="Chat is already running.")

        launch_profile_service.assert_chat_snapshot_ready(project)

        self._state._transition_chat_status(chat_id, chat, runtime_mixin.CHAT_STATUS_STARTING, "chat_start_requested")
        chat["start_error"] = ""
        chat["last_exit_code"] = None
        chat["last_exit_at"] = ""
        chat["stop_requested_at"] = ""
        chat["pid"] = None
        state["chats"][chat_id] = chat
        self._state.save(state, reason="chat_start_requested")

        try:
            with self._state._chat_input_lock:
                self._state._chat_input_buffers[chat_id] = ""
                self._state._chat_input_ansi_carry[chat_id] = ""
            artifact_publish_token = runtime_mixin._new_artifact_publish_token()
            agent_tools_token = runtime_mixin._new_agent_tools_token()
            ready_ack_guid = runtime_mixin._new_ready_ack_guid()
            launch_context = launch_profile_service.prepare_chat_launch_context(
                chat_id=chat_id,
                chat=chat,
                project=project,
                resume=resume,
                agent_tools_token=agent_tools_token,
                artifact_publish_token=artifact_publish_token,
                ready_ack_guid=ready_ack_guid,
                context_key=f"chat_start:{chat_id}",
            )
            chat["agent_type"] = str(launch_context["agent_type"])
            cmd = list(launch_context["command"])

            state = self._state.load()
            chat = state["chats"].get(chat_id)
            if chat is None:
                raise runtime_mixin.HTTPException(status_code=404, detail="Chat was removed before runtime launch.")
            chat["artifact_publish_token_hash"] = runtime_mixin._hash_artifact_publish_token(artifact_publish_token)
            chat["artifact_publish_token_issued_at"] = runtime_mixin._iso_now()
            chat["agent_tools_token_hash"] = runtime_mixin._hash_agent_tools_token(agent_tools_token)
            chat["agent_tools_token_issued_at"] = runtime_mixin._iso_now()
            chat["ready_ack_guid"] = ready_ack_guid
            chat["ready_ack_stage"] = runtime_mixin.AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED
            chat["ready_ack_at"] = ""
            chat["ready_ack_meta"] = {}
            state["chats"][chat_id] = chat
            self._state.save(state, reason="chat_start_runtime_tokens_issued")

            proc = self._state._spawn_chat_process(chat_id, cmd)
        except Exception as exc:
            detail = self._state._chat_start_error_detail(exc)
            runtime_mixin.LOGGER.warning(
                "Chat failed to start chat_id=%s project_id=%s reason=%s detail=%s",
                chat_id,
                chat.get("project_id"),
                "chat_start_failed",
                detail,
            )
            self._state._mark_chat_start_failed(chat_id, detail=detail, reason="chat_start_failed")
            if isinstance(exc, (runtime_mixin.HTTPException, TypedAgentError)):
                raise
            raise RuntimeStateError(f"Chat start failed: {detail}") from exc

        state = self._state.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Chat was removed before start completion.")
        self._state._transition_chat_status(chat_id, chat, runtime_mixin.CHAT_STATUS_RUNNING, "chat_start_succeeded")
        chat["start_error"] = ""
        chat["pid"] = proc.pid
        chat["setup_snapshot_image"] = str(launch_context["snapshot_tag"] or "")
        chat["container_workspace"] = str(launch_context["container_workspace"])
        chat["artifact_publish_token_hash"] = runtime_mixin._hash_artifact_publish_token(artifact_publish_token)
        chat["artifact_publish_token_issued_at"] = runtime_mixin._iso_now()
        chat["agent_tools_token_hash"] = runtime_mixin._hash_agent_tools_token(agent_tools_token)
        chat["agent_tools_token_issued_at"] = runtime_mixin._iso_now()
        chat["ready_ack_guid"] = str(chat.get("ready_ack_guid") or ready_ack_guid)
        chat["ready_ack_stage"] = runtime_mixin._normalize_ready_ack_stage(chat.get("ready_ack_stage"))
        chat["ready_ack_at"] = str(chat.get("ready_ack_at") or "")
        ready_ack_meta = chat.get("ready_ack_meta")
        chat["ready_ack_meta"] = ready_ack_meta if isinstance(ready_ack_meta, dict) else {}
        chat["last_started_at"] = runtime_mixin._iso_now()
        chat["stop_requested_at"] = ""
        state["chats"][chat_id] = chat
        self._state.save(state, reason="chat_start_succeeded")
        return dict(chat)

    def refresh_chat_container(self, chat_id: str) -> dict[str, Any]:
        from agent_hub import server_hubstate_runtime_mixin as runtime_mixin

        state = self._state.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat["project_id"])
        if project is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Parent project missing.")

        running = bool(chat.get("status") == "running" and runtime_mixin._is_process_running(chat.get("pid")))
        if not running:
            raise runtime_mixin.HTTPException(status_code=409, detail="Chat must be running to refresh its container.")

        is_outdated, _reason = self._state._chat_container_outdated_state(chat=chat, project=project, is_running=running)
        if not is_outdated:
            raise runtime_mixin.HTTPException(status_code=409, detail="Chat container is already up to date.")

        self._state.close_chat(chat_id)
        return self._state.start_chat(chat_id, resume=True)

    def close_chat(self, chat_id: str) -> dict[str, Any]:
        from agent_hub import server_hubstate_runtime_mixin as runtime_mixin

        state = self._state.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise runtime_mixin.HTTPException(status_code=404, detail="Chat not found.")

        stop_requested_at = runtime_mixin._iso_now()
        chat["stop_requested_at"] = stop_requested_at
        chat["status_reason"] = runtime_mixin.CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED
        chat["updated_at"] = stop_requested_at
        state["chats"][chat_id] = chat
        self._state.save(state, reason=runtime_mixin.CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED)
        pid = chat.get("pid")
        if isinstance(pid, int):
            runtime_mixin._stop_process(pid)
        self._state._close_runtime(chat_id)
        with self._state._chat_input_lock:
            self._state._chat_input_buffers.pop(chat_id, None)
            self._state._chat_input_ansi_carry.pop(chat_id, None)

        self._state._transition_chat_status(
            chat_id, chat, runtime_mixin.CHAT_STATUS_STOPPED, runtime_mixin.CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED
        )
        chat["start_error"] = ""
        chat["pid"] = None
        chat["artifact_publish_token_hash"] = ""
        chat["artifact_publish_token_issued_at"] = ""
        chat["agent_tools_token_hash"] = ""
        chat["agent_tools_token_issued_at"] = ""
        chat["last_exit_code"] = None
        chat["last_exit_at"] = runtime_mixin._iso_now()
        chat["stop_requested_at"] = ""
        state["chats"][chat_id] = chat
        self._state.save(state, reason=runtime_mixin.CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED)
        return dict(chat)


__all__ = ["RuntimeService"]
