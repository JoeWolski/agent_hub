from __future__ import annotations

from typing import Any


class RuntimeService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def runtime_flags_payload(self) -> dict[str, Any]:
        return self._state.runtime_flags_payload()


__all__ = ["RuntimeService"]
