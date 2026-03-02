from __future__ import annotations

from typing import Any


class AppStateService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def state_payload(self) -> dict[str, Any]:
        return self._state.state_payload()

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
