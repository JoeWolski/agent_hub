from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class CredentialsService:
    def __init__(self, *, domain: Any, agent_tools_token_header: str) -> None:
        self._domain = domain
        self._agent_tools_token_header = str(agent_tools_token_header)

    def resolve_token(self, headers: Mapping[str, Any]) -> str:
        return str(headers.get(self._agent_tools_token_header) or "").strip()

    def list_chat_credentials(self, *, chat_id: str, token: str) -> dict[str, Any]:
        return self._domain.list_chat_credentials(chat_id=chat_id, token=token)

    def resolve_chat_credentials(
        self,
        *,
        chat_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        return self._domain.resolve_chat_credentials(
            chat_id=chat_id,
            token=token,
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
        return self._domain.attach_chat_project_credentials(
            chat_id=chat_id,
            token=token,
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
        return self._domain.acknowledge_chat_ready(
            chat_id=chat_id,
            token=token,
            guid=guid,
            stage=stage,
            meta=meta,
        )

    def list_session_credentials(self, *, session_id: str, token: str) -> dict[str, Any]:
        return self._domain.list_session_credentials(session_id=session_id, token=token)

    def resolve_session_credentials(
        self,
        *,
        session_id: str,
        token: str,
        mode: Any,
        credential_ids: Any,
    ) -> dict[str, Any]:
        return self._domain.resolve_session_credentials(
            session_id=session_id,
            token=token,
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
        return self._domain.attach_session_project_credentials(
            session_id=session_id,
            token=token,
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
        return self._domain.acknowledge_session_ready(
            session_id=session_id,
            token=token,
            guid=guid,
            stage=stage,
            meta=meta,
        )


__all__ = ["CredentialsService"]
