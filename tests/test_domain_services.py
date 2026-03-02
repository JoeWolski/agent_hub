from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_hub.domains.auto_config_domain import AutoConfigDomain
from agent_hub.domains.chat_runtime_domain import ChatRuntimeDomain
from agent_hub.domains.credentials_domain import CredentialsDomain
from agent_hub.domains.project_domain import ProjectDomain
from agent_hub.services.artifacts_service import ArtifactsService
from agent_hub.services.auto_config_service import AutoConfigService
from agent_hub.services.chat_service import ChatService
from agent_hub.services.credentials_service import CredentialsService
from agent_hub.services.project_service import ProjectService
from agent_hub.services.runtime_service import RuntimeService


class ProjectServiceTests(unittest.TestCase):
    def test_project_build_logs_reads_log_when_present(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log_path = Path(tmp.name) / "build.log"
        log_path.write_text("build-ok\n", encoding="utf-8")

        state = SimpleNamespace(
            project=Mock(return_value={"id": "proj-1"}),
            project_build_log=Mock(return_value=log_path),
        )
        service = ProjectService(domain=ProjectDomain(state=state))

        self.assertEqual(service.project_build_logs("proj-1"), "build-ok\n")

    def test_project_build_logs_rejects_missing_project(self) -> None:
        state = SimpleNamespace(project=Mock(return_value=None))
        service = ProjectService(domain=ProjectDomain(state=state))

        with self.assertRaises(HTTPException) as raised:
            service.project_build_logs("missing")
        self.assertEqual(raised.exception.status_code, 404)


class ChatServiceTests(unittest.TestCase):
    def test_chat_logs_reads_log_when_present(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log_path = Path(tmp.name) / "chat.log"
        log_path.write_text("hi\n", encoding="utf-8")

        state = SimpleNamespace(
            chat=Mock(return_value={"id": "chat-1"}),
            chat_log=Mock(return_value=log_path),
        )
        service = ChatService(domain=ChatRuntimeDomain(state=state))

        self.assertEqual(service.chat_logs("chat-1"), "hi\n")

    def test_chat_logs_rejects_missing_chat(self) -> None:
        state = SimpleNamespace(chat=Mock(return_value=None))
        service = ChatService(domain=ChatRuntimeDomain(state=state))

        with self.assertRaises(HTTPException) as raised:
            service.chat_logs("missing")
        self.assertEqual(raised.exception.status_code, 404)


class RuntimeServiceTests(unittest.TestCase):
    def test_runtime_flags_payload_delegates(self) -> None:
        expected = {"ui_lifecycle_debug": True}
        state = SimpleNamespace(runtime_flags_payload=Mock(return_value=expected))
        service = RuntimeService(state=state)
        self.assertEqual(service.runtime_flags_payload(), expected)


class CredentialsServiceTests(unittest.TestCase):
    def test_resolve_token_prefers_bearer(self) -> None:
        service = CredentialsService(domain=SimpleNamespace(), agent_tools_token_header="x-agent-tools-token")
        headers = {"authorization": "Bearer abc", "x-agent-tools-token": "fallback"}
        self.assertEqual(service.resolve_token(headers), "abc")

    def test_list_chat_credentials_requires_existing_chat(self) -> None:
        state = SimpleNamespace(chat=Mock(return_value=None))
        service = CredentialsService(
            domain=CredentialsDomain(state=state),
            agent_tools_token_header="x-agent-tools-token",
        )
        with self.assertRaises(HTTPException) as raised:
            service.list_chat_credentials(chat_id="chat-1", token="token")
        self.assertEqual(raised.exception.status_code, 404)


class ArtifactsServiceTests(unittest.TestCase):
    def test_resolve_publish_token_uses_fallback_header(self) -> None:
        service = ArtifactsService(
            state=SimpleNamespace(),
            agent_tools_token_header="x-agent-tools-token",
            artifact_token_header="x-artifact-token",
        )
        self.assertEqual(service.resolve_artifact_publish_token({"x-artifact-token": "abc"}), "abc")

    def test_require_chat_publish_workspace_rejects_missing_workspace(self) -> None:
        state = SimpleNamespace(
            chat=Mock(return_value={"id": "chat-1"}),
            _require_artifact_publish_token=Mock(),
            chat_workdir=Mock(return_value=Path(tempfile.gettempdir()) / "definitely-missing-dir-agent-hub"),
        )
        service = ArtifactsService(
            state=state,
            agent_tools_token_header="x-agent-tools-token",
            artifact_token_header="x-artifact-token",
        )
        with self.assertRaises(HTTPException) as raised:
            service.require_chat_publish_workspace(chat_id="chat-1", token="token")
        self.assertEqual(raised.exception.status_code, 409)


class AutoConfigServiceTests(unittest.TestCase):
    def test_auto_configure_project_delegates(self) -> None:
        state = SimpleNamespace(auto_configure_project=Mock(return_value={"ok": True}))
        service = AutoConfigService(domain=AutoConfigDomain(state=state))
        self.assertEqual(
            service.auto_configure_project(repo_url="https://example.com/repo.git"),
            {"ok": True},
        )


if __name__ == "__main__":
    unittest.main()
