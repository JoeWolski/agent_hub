from __future__ import annotations

from typing import Any


class LifecycleService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def forward_openai_account_callback(
        self,
        query: str,
        *,
        path: str = "/auth/callback",
        request_host: str = "",
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._state.forward_openai_account_callback(
            query,
            path=path,
            request_host=request_host,
            request_context=request_context,
        )

    def shutdown(self) -> dict[str, int]:
        return self._state.shutdown()
