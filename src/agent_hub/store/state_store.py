from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from agent_core.errors import StateStoreError

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

    def load(
        self,
        *,
        normalizer: Callable[[dict[str, Any]], tuple[dict[str, Any], bool]] | None = None,
        target_version: int | None = None,
        migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            loaded = self._load_raw_locked()
            migrated_state, migrated_changed = self._apply_migrations_locked(
                loaded,
                target_version=target_version,
                migrations=migrations,
            )
            if normalizer is None:
                if migrated_changed:
                    self._write_locked(migrated_state)
                return migrated_state
            normalized, changed = normalizer(migrated_state)
            if not isinstance(normalized, dict):
                raise StateStoreError("State normalizer must return a JSON object.")
            if migrated_changed or changed:
                self._write_locked(normalized)
        return normalized

    def load_raw(self) -> dict[str, Any]:
        with self._lock:
            loaded = self._load_raw_locked()
        return loaded

    def save_raw(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._write_locked(state)

    def _load_raw_locked(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return self._new_state_factory()
        try:
            loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            preserved_state_path = self._preserve_corrupt_state_file_locked()
            raise StateStoreError(
                f"State file is corrupt JSON and was moved to {preserved_state_path}."
            ) from exc
        if not isinstance(loaded, dict):
            preserved_state_path = self._preserve_corrupt_state_file_locked()
            raise StateStoreError(
                "State file must contain a JSON object and was moved to "
                f"{preserved_state_path}."
            )
        return loaded

    def _write_locked(self, state: dict[str, Any]) -> None:
        with self.state_file.open("w", encoding="utf-8") as fp:
            json.dump(state, fp, indent=2)

    @staticmethod
    def _normalized_state_version(state: dict[str, Any]) -> int:
        raw_version = state.get("version")
        if raw_version is None:
            return 1
        if isinstance(raw_version, bool):
            raise StateStoreError("State version must be an integer.")
        if isinstance(raw_version, int):
            if raw_version < 0:
                raise StateStoreError("State version must be non-negative.")
            return raw_version
        if isinstance(raw_version, str) and raw_version.strip():
            try:
                parsed = int(raw_version.strip())
            except ValueError as exc:
                raise StateStoreError("State version must be an integer.") from exc
            if parsed < 0:
                raise StateStoreError("State version must be non-negative.")
            return parsed
        raise StateStoreError("State version must be an integer.")

    def _apply_migrations_locked(
        self,
        loaded: dict[str, Any],
        *,
        target_version: int | None,
        migrations: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] | None,
    ) -> tuple[dict[str, Any], bool]:
        if target_version is None:
            return loaded, False
        normalized_target = int(target_version)
        if normalized_target < 0:
            raise StateStoreError("State target version must be non-negative.")
        migration_map = dict(migrations or {})
        state = loaded
        changed = False
        version = self._normalized_state_version(state)
        if version > normalized_target:
            raise StateStoreError(
                f"State version {version} is newer than supported target version {normalized_target}."
            )
        while version < normalized_target:
            migrate_step = migration_map.get(version)
            if migrate_step is None:
                raise StateStoreError(
                    f"Missing migration step for state version {version} -> {version + 1}."
                )
            migrated = migrate_step(state)
            if not isinstance(migrated, dict):
                raise StateStoreError(
                    f"Migration for state version {version} -> {version + 1} must return a JSON object."
                )
            state = dict(migrated)
            state["version"] = version + 1
            version += 1
            changed = True
        if changed:
            return state, True
        return state, False

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
            raise StateStoreError(
                f"Failed to preserve corrupt state file {self.state_file}: {exc}"
            ) from exc
        return preserved_path
