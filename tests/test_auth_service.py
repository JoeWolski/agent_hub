from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_hub.services.auth_service import AuthCallbackForwardResult, AuthService


class _FakeResponse:
    def __init__(self, *, code: int, body: str) -> None:
        self._code = code
        self._body = body

    def getcode(self) -> int:
        return self._code

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class AuthServiceTests(unittest.TestCase):
    def _service(self, domain: object | None = None) -> AuthService:
        return AuthService(
            domain=domain or SimpleNamespace(),
            default_artifact_publish_host="localhost",
            callback_forward_timeout_seconds=0.2,
        )

    def test_connect_openai_wraps_provider_payload(self) -> None:
        domain = SimpleNamespace(connect_openai=Mock(return_value={"connected": True}))
        payload = self._service(domain).connect_openai("sk-test", verify=True)
        self.assertEqual(payload, {"provider": {"connected": True}})
        domain.connect_openai.assert_called_once_with("sk-test", verify=True)

    def test_candidate_hosts_prefers_configured_url_with_single_bridge_fallback(self) -> None:
        service = self._service()
        hosts, diagnostics = service._candidate_hosts(
            artifact_publish_base_url="http://bridge.example:8876",
            request_host="ignored",
            request_context={"x": "y"},
            discover_bridge_hosts=lambda: (["bridge.example", "10.0.0.8", "10.0.0.8"], {"source": "bridge"}),
            normalize_host=lambda value: str(value or "").strip().lower(),
        )
        self.assertEqual(hosts, ["bridge.example"])
        self.assertEqual(diagnostics, {"source": "bridge"})

    def test_candidate_hosts_uses_first_bridge_when_configured_host_missing(self) -> None:
        service = self._service()
        hosts, diagnostics = service._candidate_hosts(
            artifact_publish_base_url="",
            request_host="ignored",
            request_context={},
            discover_bridge_hosts=lambda: (["10.0.0.8", "10.0.0.9"], {"source": "bridge"}),
            normalize_host=lambda value: str(value or "").strip().lower(),
        )
        self.assertEqual(hosts, ["localhost", "10.0.0.8"])
        self.assertEqual(diagnostics, {"source": "bridge"})

    def test_forward_openai_account_callback_returns_response_payload(self) -> None:
        logger = Mock()
        service = self._service()
        session = SimpleNamespace(id="s-1", container_name="c-1")

        with patch("agent_hub.services.auth_service.urllib.request.urlopen", return_value=_FakeResponse(code=200, body="ok")):
            result = service.forward_openai_account_callback(
                session=session,
                callback_port=8877,
                callback_path="/oauth/callback",
                query="code=abc&state=def",
                artifact_publish_base_url="http://127.0.0.1:8876",
                request_host="127.0.0.1",
                request_context={},
                discover_bridge_hosts=lambda: ([], {"bridge": "none"}),
                normalize_host=lambda value: str(value or "").strip(),
                callback_query_summary=lambda query: {"raw": query},
                redact_url_query_values=lambda url: url,
                host_port_netloc=lambda host, port: f"{host}:{port}",
                classify_callback_error=lambda exc: type(exc).__name__,
                logger=logger,
            )

        self.assertIsInstance(result, AuthCallbackForwardResult)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.response_body, "ok")
        self.assertEqual(result.target_origin, "http://127.0.0.1:8877")

    def test_forward_openai_account_callback_raises_502_when_all_hosts_fail(self) -> None:
        logger = Mock()
        service = self._service()
        session = SimpleNamespace(id="s-1", container_name="c-1")

        def fail_urlopen(*args, **kwargs):
            raise OSError("connection refused")

        with patch("agent_hub.services.auth_service.urllib.request.urlopen", side_effect=fail_urlopen):
            with self.assertRaises(HTTPException) as raised:
                service.forward_openai_account_callback(
                    session=session,
                    callback_port=8877,
                    callback_path="/oauth/callback",
                    query="code=abc",
                    artifact_publish_base_url="http://host-a:8876",
                    request_host="127.0.0.1",
                    request_context={},
                    discover_bridge_hosts=lambda: (["host-b"], {}),
                    normalize_host=lambda value: str(value or "").strip(),
                    callback_query_summary=lambda query: {"raw": query},
                    redact_url_query_values=lambda url: url,
                    host_port_netloc=lambda host, port: f"{host}:{port}",
                    classify_callback_error=lambda exc: "connection_refused",
                    logger=logger,
                )

        self.assertEqual(raised.exception.status_code, 502)
        self.assertIn("connection_refused", str(raised.exception.detail))
        self.assertIn("http://host-a:8877", str(raised.exception.detail))
        self.assertIn("http://host-b:8877", str(raised.exception.detail))


if __name__ == "__main__":
    unittest.main()
