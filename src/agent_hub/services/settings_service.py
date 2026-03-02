from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException


def _compact_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _normalize_git_identity_setting(raw_value: Any, *, field_name: str, strict: bool = False) -> str:
    raw_text = str(raw_value or "").strip()
    if any(char in raw_text for char in ("\r", "\n", "\x00")):
        if strict:
            raise HTTPException(status_code=400, detail=f"{field_name} must not contain control characters.")
        raw_text = raw_text.replace("\r", " ").replace("\n", " ").replace("\x00", "")
    value = _compact_whitespace(raw_text)
    if len(value) > 256:
        if strict:
            raise HTTPException(status_code=400, detail=f"{field_name} must be 256 characters or fewer.")
        value = value[:256].strip()
    return value


class SettingsService:
    def __init__(
        self,
        *,
        default_agent_type: str,
        default_chat_layout_engine: str,
        normalize_chat_agent_type: Callable[..., str],
        normalize_chat_layout_engine: Callable[..., str],
    ):
        self._default_agent_type = str(default_agent_type)
        self._default_chat_layout_engine = str(default_chat_layout_engine)
        self._normalize_chat_agent_type = normalize_chat_agent_type
        self._normalize_chat_layout_engine = normalize_chat_layout_engine

    def empty_settings_payload(self) -> dict[str, Any]:
        return {
            "default_agent_type": self._default_agent_type,
            "chat_layout_engine": self._default_chat_layout_engine,
            "git_user_name": "",
            "git_user_email": "",
        }

    def normalize_settings_payload(self, raw_settings: Any) -> dict[str, Any]:
        if not isinstance(raw_settings, dict):
            raw_settings = {}
        normalized = {
            "default_agent_type": self._normalize_chat_agent_type(
                raw_settings.get("default_agent_type") or raw_settings.get("defaultAgentType")
            ),
            "chat_layout_engine": self._normalize_chat_layout_engine(
                raw_settings.get("chat_layout_engine") or raw_settings.get("chatLayoutEngine")
            ),
            "git_user_name": _normalize_git_identity_setting(
                raw_settings.get("git_user_name", raw_settings.get("gitUserName")),
                field_name="git_user_name",
            ),
            "git_user_email": _normalize_git_identity_setting(
                raw_settings.get("git_user_email", raw_settings.get("gitUserEmail")),
                field_name="git_user_email",
            ),
        }
        if bool(normalized["git_user_name"]) != bool(normalized["git_user_email"]):
            normalized["git_user_name"] = ""
            normalized["git_user_email"] = ""
        return normalized

    def settings_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        return self.normalize_settings_payload(state.get("settings"))

    def update_settings(self, state: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(update, dict):
            raise HTTPException(status_code=400, detail="Invalid settings payload.")
        has_default_agent_type = "default_agent_type" in update or "defaultAgentType" in update
        has_chat_layout_engine = "chat_layout_engine" in update or "chatLayoutEngine" in update
        has_git_user_name = "git_user_name" in update or "gitUserName" in update
        has_git_user_email = "git_user_email" in update or "gitUserEmail" in update
        if not has_default_agent_type and not has_chat_layout_engine and not has_git_user_name and not has_git_user_email:
            raise HTTPException(status_code=400, detail="No settings values provided.")

        settings = self.normalize_settings_payload(state.get("settings"))
        if has_default_agent_type:
            settings["default_agent_type"] = self._normalize_chat_agent_type(
                update.get("default_agent_type", update.get("defaultAgentType")),
                strict=True,
            )
        if has_chat_layout_engine:
            settings["chat_layout_engine"] = self._normalize_chat_layout_engine(
                update.get("chat_layout_engine", update.get("chatLayoutEngine")),
                strict=True,
            )
        if has_git_user_name:
            settings["git_user_name"] = _normalize_git_identity_setting(
                update.get("git_user_name", update.get("gitUserName")),
                field_name="git_user_name",
                strict=True,
            )
        if has_git_user_email:
            settings["git_user_email"] = _normalize_git_identity_setting(
                update.get("git_user_email", update.get("gitUserEmail")),
                field_name="git_user_email",
                strict=True,
            )
        if bool(settings["git_user_name"]) != bool(settings["git_user_email"]):
            raise HTTPException(
                status_code=400,
                detail="git_user_name and git_user_email must both be set or both be empty.",
            )
        return settings


__all__ = ["SettingsService"]
