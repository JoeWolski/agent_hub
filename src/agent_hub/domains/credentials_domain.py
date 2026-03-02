from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class CredentialsDomain:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def list_chat_credentials(self, *, chat_id: str, token: str) -> dict[str, Any]:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._state._require_agent_tools_token(chat, token)
        return self._state.agent_tools_credentials_list_payload(chat_id)

    def resolve_chat_credentials(
        self,
        *,
        chat_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._state._require_agent_tools_token(chat, token)
        return self._state.resolve_agent_tools_credentials(
            chat_id=chat_id,
            mode=mode,
            credential_ids=credential_ids,
        )

    def attach_chat_project_credentials(
        self,
        *,
        chat_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._state._require_agent_tools_token(chat, token)
        return self._state.attach_agent_tools_project_credentials(
            chat_id=chat_id,
            mode=mode,
            credential_ids=credential_ids,
        )

    def acknowledge_chat_ready(
        self,
        *,
        chat_id: str,
        token: str,
        guid: Any,
        stage: Any,
        meta: Any,
    ) -> dict[str, Any]:
        return self._state.acknowledge_agent_tools_chat_ready(
            chat_id=chat_id,
            token=token,
            guid=guid,
            stage=stage,
            meta=meta,
        )

    def list_session_credentials(self, *, session_id: str, token: str) -> dict[str, Any]:
        self._state.require_agent_tools_session_token(session_id, token)
        return self._state.agent_tools_session_credentials_list_payload(session_id)

    def resolve_session_credentials(
        self,
        *,
        session_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        self._state.require_agent_tools_session_token(session_id, token)
        return self._state.resolve_agent_tools_session_credentials(
            session_id=session_id,
            mode=mode,
            credential_ids=credential_ids,
        )

    def attach_session_project_credentials(
        self,
        *,
        session_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        self._state.require_agent_tools_session_token(session_id, token)
        return self._state.attach_agent_tools_session_project_credentials(
            session_id=session_id,
            mode=mode,
            credential_ids=credential_ids,
        )

    def acknowledge_session_ready(
        self,
        *,
        session_id: str,
        token: str,
        guid: Any,
        stage: Any,
        meta: Any,
    ) -> dict[str, Any]:
        return self._state.acknowledge_agent_tools_session_ready(
            session_id=session_id,
            token=token,
            guid=guid,
            stage=stage,
            meta=meta,
        )

