from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable


class HubStateStore:
    def __init__(
        self,
        *,
        state_file: Path,
        lock: Lock,
        new_state_factory: Callable[[], dict[str, Any]],
    ) -> None:
        self.state_file = Path(state_file)
        self._lock = lock
        self._new_state_factory = new_state_factory

    def load_raw(self) -> dict[str, Any]:
        with self._lock:
            if not self.state_file.exists():
                return self._new_state_factory()
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                preserved_state_path = self._preserve_corrupt_state_file_locked()
                raise RuntimeError(
                    f"State file is corrupt JSON and was moved to {preserved_state_path}."
                ) from exc
            if not isinstance(loaded, dict):
                preserved_state_path = self._preserve_corrupt_state_file_locked()
                raise RuntimeError(
                    "State file must contain a JSON object and was moved to "
                    f"{preserved_state_path}."
                )
        return loaded

    def save_raw(self, state: dict[str, Any]) -> None:
        with self._lock:
            with self.state_file.open("w", encoding="utf-8") as fp:
                json.dump(state, fp, indent=2)

    def _preserve_corrupt_state_file_locked(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base_name = f"{self.state_file.name}.corrupt-{timestamp}"
        preserved_path = self.state_file.with_name(base_name)
        suffix = 1
        while preserved_path.exists():
            preserved_path = self.state_file.with_name(f"{base_name}.{suffix}")
            suffix += 1
        try:
            self.state_file.replace(preserved_path)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to preserve corrupt state file {self.state_file}: {exc}"
            ) from exc
        return preserved_path
