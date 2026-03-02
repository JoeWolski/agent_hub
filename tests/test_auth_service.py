from __future__ import annotations

import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core.errors import NetworkReachabilityError
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
            discover_bridge_hosts=lambda: (["bridge.example", "10.0.0.8", "10.0.0.8"], {"source": "bridge"}),
            normalize_host=lambda value: str(value or "").strip().lower(),
        )
        self.assertEqual(hosts, ["bridge.example"])
        self.assertEqual(diagnostics, {"source": "bridge"})

    def test_candidate_hosts_uses_first_bridge_when_configured_host_missing(self) -> None:
        service = self._service()
        hosts, diagnostics = service._candidate_hosts(
            artifact_publish_base_url="",
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
        info_calls = [call for call in logger.info.call_args_list if "extra" in call.kwargs]
        self.assertGreaterEqual(len(info_calls), 2)
        for call in info_calls:
            extra = call.kwargs["extra"]
            self.assertIsInstance(extra.get("duration_ms"), int)
            self.assertGreaterEqual(int(extra.get("duration_ms", -1)), 0)
            self.assertEqual(extra.get("error_class"), "none")

    def test_forward_openai_account_callback_raises_network_reachability_error_when_all_hosts_fail_with_oserror(
        self,
    ) -> None:
        logger = Mock()
        service = self._service()
        session = SimpleNamespace(id="s-1", container_name="c-1")
        with patch("agent_hub.services.auth_service.urllib.request.urlopen", side_effect=OSError("connection refused")):
            with self.assertRaises(NetworkReachabilityError) as raised:
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

        detail = str(raised.exception)
        self.assertIn("Reason: connection_refused", detail)
        self.assertIn("http://host-a:8877", detail)
        self.assertIn("http://host-b:8877", detail)

    def test_forward_openai_account_callback_raises_network_reachability_error_when_all_hosts_fail_with_urlerror(
        self,
    ) -> None:
        logger = Mock()
        service = self._service()
        session = SimpleNamespace(id="s-1", container_name="c-1")
        with patch(
            "agent_hub.services.auth_service.urllib.request.urlopen",
            side_effect=urllib.error.URLError("lookup failure"),
        ):
            with self.assertRaises(NetworkReachabilityError) as raised:
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
                    classify_callback_error=lambda exc: "dns_error",
                    logger=logger,
                )

        detail = str(raised.exception)
        self.assertIn("Reason: dns_error", detail)
        self.assertIn("http://host-a:8877", detail)
        self.assertIn("http://host-b:8877", detail)

    def test_forward_openai_account_callback_raises_network_reachability_error_when_all_hosts_fail_with_timeout(
        self,
    ) -> None:
        logger = Mock()
        service = self._service()
        session = SimpleNamespace(id="s-1", container_name="c-1")
        with patch("agent_hub.services.auth_service.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(NetworkReachabilityError) as raised:
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
                    classify_callback_error=lambda exc: "timeout",
                    logger=logger,
                )

        detail = str(raised.exception)
        self.assertIn("Reason: timeout", detail)
        self.assertIn("http://host-a:8877", detail)
        self.assertIn("http://host-b:8877", detail)


if __name__ == "__main__":
    unittest.main()
