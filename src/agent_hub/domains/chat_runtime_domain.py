from __future__ import annotations

import queue
from typing import Any

from fastapi import HTTPException


class ChatRuntimeDomain:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def chat(self, chat_id: str) -> dict[str, Any] | None:
        return self._state.chat(chat_id)

    def create_chat(
        self,
        *,
        project_id: str,
        profile: str | None,
        ro_mounts: list[str],
        rw_mounts: list[str],
        env_vars: list[str],
        agent_args: list[str],
        agent_type: str,
    ) -> dict[str, Any]:
        return self._state.create_chat(
            project_id,
            profile,
            ro_mounts,
            rw_mounts,
            env_vars,
            agent_args=agent_args,
            agent_type=agent_type,
        )

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
        self._state._queue_put(listener, value)

