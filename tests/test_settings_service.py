from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import HTTPException

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_hub.services.settings_service import SettingsService


class SettingsServiceTests(unittest.TestCase):
    def _service(self) -> SettingsService:
        def normalize_agent_type(value: object, strict: bool = False) -> str:
            normalized = str(value or "").strip().lower() or "codex"
            allowed = {"codex", "openai"}
            if strict and normalized not in allowed:
                raise HTTPException(status_code=400, detail="invalid default_agent_type")
            return normalized if normalized in allowed else "codex"

        def normalize_layout_engine(value: object, strict: bool = False) -> str:
            normalized = str(value or "").strip().lower() or "flex"
            allowed = {"flex", "stack"}
            if strict and normalized not in allowed:
                raise HTTPException(status_code=400, detail="invalid chat_layout_engine")
            return normalized if normalized in allowed else "flex"

        return SettingsService(
            default_agent_type="codex",
            default_chat_layout_engine="flex",
            normalize_chat_agent_type=normalize_agent_type,
            normalize_chat_layout_engine=normalize_layout_engine,
        )

    def test_empty_settings_payload_uses_config_defaults(self) -> None:
        payload = self._service().empty_settings_payload()
        self.assertEqual(payload["default_agent_type"], "codex")
        self.assertEqual(payload["chat_layout_engine"], "flex")
        self.assertEqual(payload["git_user_name"], "")
        self.assertEqual(payload["git_user_email"], "")

    def test_normalize_settings_payload_accepts_camel_case_keys(self) -> None:
        payload = self._service().normalize_settings_payload(
            {
                "defaultAgentType": " OPENAI ",
                "chatLayoutEngine": " STACK ",
                "gitUserName": " Jane  Doe ",
                "gitUserEmail": " jane@example.com ",
            }
        )
        self.assertEqual(payload["default_agent_type"], "openai")
        self.assertEqual(payload["chat_layout_engine"], "stack")
        self.assertEqual(payload["git_user_name"], "Jane Doe")
        self.assertEqual(payload["git_user_email"], "jane@example.com")

    def test_normalize_settings_payload_clears_partial_git_identity(self) -> None:
        payload = self._service().normalize_settings_payload({"git_user_name": "Only Name"})
        self.assertEqual(payload["git_user_name"], "")
        self.assertEqual(payload["git_user_email"], "")

    def test_update_settings_rejects_empty_update(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._service().update_settings({"settings": {}}, {})
        self.assertEqual(raised.exception.status_code, 400)

    def test_update_settings_requires_git_identity_pair(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._service().update_settings({"settings": {}}, {"git_user_name": "Jane Doe"})
        self.assertEqual(raised.exception.status_code, 400)

    def test_update_settings_applies_strict_normalization(self) -> None:
        settings = self._service().update_settings(
            {"settings": {"default_agent_type": "codex", "chat_layout_engine": "flex"}},
            {
                "defaultAgentType": "openai",
                "chatLayoutEngine": "stack",
                "gitUserName": "Jane Doe",
                "gitUserEmail": "jane@example.com",
            },
        )
        self.assertEqual(settings["default_agent_type"], "openai")
        self.assertEqual(settings["chat_layout_engine"], "stack")
        self.assertEqual(settings["git_user_name"], "Jane Doe")
        self.assertEqual(settings["git_user_email"], "jane@example.com")


if __name__ == "__main__":
    unittest.main()
