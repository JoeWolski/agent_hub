from __future__ import annotations

import queue
import uuid
from typing import Any

from fastapi import HTTPException


def _hub_server_module() -> Any:
    import agent_hub.server as _hub_server

    return _hub_server


class ChatService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def create_chat(
        self,
        *,
        project_id: str,
        profile: str | None,
        ro_mounts: list[str],
        rw_mounts: list[str],
        env_vars: list[str],
        agent_args: list[str] | None,
        agent_type: str | None,
        create_request_id: str | None = None,
    ) -> dict[str, Any]:
        _hub_server = _hub_server_module()

        state = self._state.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        chat_id = uuid.uuid4().hex
        now = _hub_server._iso_now()
        sanitized_project_name = _hub_server._sanitize_workspace_component(project.get("name") or project_id)
        workspace_path = self._state.chat_dir / f"{sanitized_project_name}_{chat_id}"
        container_workspace = _hub_server._container_workspace_path_for_project(project.get("name") or project_id)
        chat = {
            "id": chat_id,
            "project_id": project_id,
            "name": _hub_server.CHAT_DEFAULT_NAME,
            "profile": profile or "",
            "ro_mounts": ro_mounts,
            "rw_mounts": rw_mounts,
            "env_vars": env_vars,
            "agent_args": agent_args or [],
            "agent_type": _hub_server._resolve_optional_chat_agent_type(
                agent_type,
                default_value=self._state.default_chat_agent_type(),
            ),
            "status": _hub_server.CHAT_STATUS_STOPPED,
            "status_reason": _hub_server.CHAT_STATUS_REASON_CHAT_CREATED,
            "last_status_transition_at": now,
            "start_error": "",
            "last_exit_code": None,
            "last_exit_at": "",
            "stop_requested_at": "",
            "pid": None,
            "workspace": str(workspace_path),
            "container_workspace": container_workspace,
            "title_user_prompts": [],
            "title_cached": "",
            "title_prompt_fingerprint": "",
            "title_source": "openai",
            "title_status": "idle",
            "title_error": "",
            "artifacts": [],
            "artifact_current_ids": [],
            "artifact_prompt_history": [],
            "artifact_publish_token_hash": "",
            "artifact_publish_token_issued_at": "",
            "agent_tools_token_hash": "",
            "agent_tools_token_issued_at": "",
            "ready_ack_guid": "",
            "ready_ack_stage": _hub_server.AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
            "ready_ack_at": "",
            "ready_ack_meta": {},
            "create_request_id": _hub_server._compact_whitespace(str(create_request_id or "")).strip(),
            "created_at": now,
            "updated_at": now,
        }
        state["chats"][chat_id] = chat
        self._state.save(state, reason=_hub_server.CHAT_STATUS_REASON_CHAT_CREATED)
        _hub_server.LOGGER.info(
            "Chat state transition chat_id=%s from=%s to=%s reason=%s",
            chat_id,
            "missing",
            _hub_server.CHAT_STATUS_STOPPED,
            _hub_server.CHAT_STATUS_REASON_CHAT_CREATED,
        )
        return chat

    def update_chat(self, chat_id: str, update: dict[str, Any]) -> dict[str, Any]:
        return self._state.update_chat(chat_id, update)

    def delete_chat(self, chat_id: str) -> None:
        self._state.delete_chat(chat_id)

    def record_chat_title_prompt(self, chat_id: str, prompt: Any) -> dict[str, Any]:
        return self._state.record_chat_title_prompt(chat_id, prompt)

    def chat_logs(self, chat_id: str) -> str:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        log_path = self._state.chat_log(chat_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    def start_chat(self, chat_id: str) -> dict[str, Any]:
        return self._state.start_chat(chat_id)

    def chat_launch_profile(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]:
        return self._state.chat_launch_profile(chat_id, resume=resume)

    def refresh_chat_container(self, chat_id: str) -> dict[str, Any]:
        return self._state.refresh_chat_container(chat_id)

    def close_chat(self, chat_id: str) -> dict[str, Any]:
        return self._state.close_chat(chat_id)

    def chat(self, chat_id: str) -> dict[str, Any] | None:
        return self._state.chat(chat_id)

    def attach_terminal(self, chat_id: str) -> tuple[queue.Queue[str | None], str]:
        return self._state.attach_terminal(chat_id)

    def detach_terminal(self, chat_id: str, listener: queue.Queue[str | None]) -> None:
        self._state.detach_terminal(chat_id, listener)

    def write_terminal_input(self, chat_id: str, data: str) -> None:
        self._state.write_terminal_input(chat_id, data)

    def resize_terminal(self, chat_id: str, cols: int, rows: int) -> None:
        self._state.resize_terminal(chat_id, cols, rows)

    def submit_chat_input_buffer(self, chat_id: str) -> None:
        self._state.submit_chat_input_buffer(chat_id)

    def queue_put(self, listener: queue.Queue[str | None], value: str | None) -> None:
        self._state.queue_put(listener, value)


__all__ = ["ChatService"]
