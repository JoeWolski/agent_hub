from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import HTTPException


class ArtifactsService:
    def __init__(
        self,
        *,
        state: Any,
        agent_tools_token_header: str,
        artifact_token_header: str,
    ) -> None:
        self._state = state
        self._agent_tools_token_header = str(agent_tools_token_header)
        self._artifact_token_header = str(artifact_token_header)

    @staticmethod
    def _bearer_token(headers: Mapping[str, Any]) -> str:
        auth_header = str(headers.get("authorization") or "")
        if auth_header.lower().startswith("bearer "):
            return auth_header[7:].strip()
        return ""

    def resolve_artifact_publish_token(self, headers: Mapping[str, Any]) -> str:
        token = self._bearer_token(headers)
        if not token:
            token = str(headers.get(self._artifact_token_header) or "").strip()
        return token

    def resolve_agent_tools_token(self, headers: Mapping[str, Any]) -> str:
        token = self._bearer_token(headers)
        if not token:
            token = str(headers.get(self._agent_tools_token_header) or "").strip()
        return token

    def list_chat_artifacts(self, chat_id: str) -> list[dict[str, Any]]:
        return self._state.list_chat_artifacts(chat_id)

    def require_chat_publish_workspace(self, *, chat_id: str, token: Any) -> Path:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._state._require_artifact_publish_token(chat, token)
        workspace = self._state.chat_workdir(chat_id).resolve()
        if not workspace.exists():
            raise HTTPException(status_code=409, detail="Chat workspace is unavailable.")
        return workspace

    def publish_chat_artifact(self, *, chat_id: str, token: Any, submitted_path: Any, name: Any) -> dict[str, Any]:
        return self._state.publish_chat_artifact(
            chat_id=chat_id,
            token=token,
            submitted_path=submitted_path,
            name=name,
        )

    def resolve_chat_artifact_download(self, chat_id: str, artifact_id: str) -> tuple[Path, str, str]:
        return self._state.resolve_chat_artifact_download(chat_id, artifact_id)

    def resolve_chat_artifact_preview(self, chat_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._state.resolve_chat_artifact_preview(chat_id, artifact_id)

    def require_chat_submit_workspace(self, *, chat_id: str, token: Any) -> Path:
        chat = self._state.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._state._require_agent_tools_token(chat, token)
        workspace = self._state.chat_workdir(chat_id).resolve()
        if not workspace.exists():
            raise HTTPException(status_code=409, detail="Chat workspace is unavailable.")
        return workspace

    def submit_chat_artifact(self, *, chat_id: str, token: Any, submitted_path: Any, name: Any) -> dict[str, Any]:
        return self._state.submit_chat_artifact(
            chat_id=chat_id,
            token=token,
            submitted_path=submitted_path,
            name=name,
        )

    def require_session_publish_workspace(self, *, session_id: str, token: Any) -> Path:
        session = self._state._agent_tools_session(session_id)
        self._state._require_session_artifact_publish_token(session, token)
        workspace = Path(str(session.get("workspace") or "")).resolve()
        if not workspace.exists():
            raise HTTPException(status_code=409, detail="Session workspace is unavailable.")
        return workspace

    def publish_session_artifact(
        self,
        *,
        session_id: str,
        token: Any,
        submitted_path: Any,
        name: Any,
    ) -> dict[str, Any]:
        return self._state.publish_session_artifact(
            session_id=session_id,
            token=token,
            submitted_path=submitted_path,
            name=name,
        )

    def require_session_submit_workspace(self, *, session_id: str, token: Any) -> Path:
        session = self._state.require_agent_tools_session_token(session_id, token)
        workspace = Path(str(session.get("workspace") or "")).resolve()
        if not workspace.exists():
            raise HTTPException(status_code=409, detail="Session workspace is unavailable.")
        return workspace

    def submit_session_artifact(
        self,
        *,
        session_id: str,
        token: Any,
        submitted_path: Any,
        name: Any,
    ) -> dict[str, Any]:
        return self._state.submit_session_artifact(
            session_id=session_id,
            token=token,
            submitted_path=submitted_path,
            name=name,
        )

    def resolve_session_artifact_download(self, session_id: str, artifact_id: str) -> tuple[Path, str, str]:
        return self._state.resolve_session_artifact_download(session_id, artifact_id)

    def resolve_session_artifact_preview(self, session_id: str, artifact_id: str) -> tuple[Path, str]:
        return self._state.resolve_session_artifact_preview(session_id, artifact_id)


__all__ = ["ArtifactsService"]
