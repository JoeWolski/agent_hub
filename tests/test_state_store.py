from __future__ import annotations

import json
import tempfile
from pathlib import Path
from threading import Lock

import pytest

from agent_hub.store import HubStateStore


def _new_state() -> dict[str, object]:
    return {"version": 1, "projects": {}, "chats": {}, "settings": {}}


def _store_for(path: Path) -> HubStateStore:
    return HubStateStore(state_file=path, lock=Lock(), new_state_factory=_new_state)


def test_load_with_normalizer_persists_when_changed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        state_file.write_text(json.dumps({"version": 1}), encoding="utf-8")
        store = _store_for(state_file)

        def normalize(loaded: dict[str, object]) -> tuple[dict[str, object], bool]:
            normalized = dict(loaded)
            normalized["projects"] = {}
            return normalized, True

        loaded = store.load(normalizer=normalize)
        assert loaded["projects"] == {}
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted["projects"] == {}


def test_load_with_normalizer_skips_write_when_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        original = {"version": 1, "projects": {}, "chats": {}, "settings": {}}
        state_file.write_text(json.dumps(original, indent=2), encoding="utf-8")
        before = state_file.read_text(encoding="utf-8")
        store = _store_for(state_file)

        loaded = store.load(normalizer=lambda current: (dict(current), False))
        assert loaded == original
        assert state_file.read_text(encoding="utf-8") == before


def test_load_with_normalizer_error_does_not_write_partial_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        state_file = Path(tmp) / "state.json"
        original = {"version": 1, "projects": {}, "chats": {}, "settings": {}}
        state_file.write_text(json.dumps(original, indent=2), encoding="utf-8")
        store = _store_for(state_file)

        def raising_normalizer(_: dict[str, object]) -> tuple[dict[str, object], bool]:
            raise RuntimeError("normalize failed")

        with pytest.raises(RuntimeError, match="normalize failed"):
            store.load(normalizer=raising_normalizer)
        persisted = json.loads(state_file.read_text(encoding="utf-8"))
        assert persisted == original
