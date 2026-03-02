from __future__ import annotations

import queue
from typing import Any


class EventService:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def attach_events(self) -> queue.Queue[dict[str, Any] | None]:
        return self._state.attach_events()

    def detach_events(self, listener: queue.Queue[dict[str, Any] | None]) -> None:
        self._state.detach_events(listener)

    def queue_put(self, listener: queue.Queue[dict[str, Any] | None], value: dict[str, Any] | None) -> None:
        self._state._event_queue_put(listener, value)

    def events_snapshot(self) -> dict[str, Any]:
        return self._state.events_snapshot()
