from __future__ import annotations

from collections.abc import Callable
from typing import Any


class LifecycleService:
    def __init__(
        self,
        *,
        forward_openai_account_callback_fn: Callable[..., dict[str, Any]],
        shutdown_fn: Callable[[], dict[str, int]],
    ) -> None:
        self._forward_openai_account_callback_fn = forward_openai_account_callback_fn
        self._shutdown_fn = shutdown_fn

    def forward_openai_account_callback(
        self,
        query: str,
        *,
        path: str = "/auth/callback",
        request_host: str = "",
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._forward_openai_account_callback_fn(
            query,
            path=path,
            request_host=request_host,
            request_context=request_context,
        )

    def shutdown(self) -> dict[str, int]:
        return self._shutdown_fn()
