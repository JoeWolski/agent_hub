from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException


@dataclass
class AuthCallbackForwardResult:
    status_code: int
    response_body: str
    target_origin: str


class AuthService:
    def __init__(
        self,
        *,
        domain: Any,
        default_artifact_publish_host: str,
        callback_forward_timeout_seconds: float,
    ) -> None:
        self._domain = domain
        self.default_artifact_publish_host = str(default_artifact_publish_host or "")
        self.callback_forward_timeout_seconds = float(callback_forward_timeout_seconds)

    def auth_settings_payload(self) -> dict[str, Any]:
        return self._domain.auth_settings_payload()

    def connect_openai(self, api_key: Any, *, verify: bool) -> dict[str, Any]:
        return {"provider": self._domain.connect_openai(api_key, verify=verify)}

    def disconnect_openai(self) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_openai()}

    def connect_github_app(self, installation_id: Any) -> dict[str, Any]:
        return {"provider": self._domain.connect_github_app(installation_id)}

    def start_github_app_setup(self, *, origin: Any) -> dict[str, Any]:
        return self._domain.start_github_app_setup(origin=origin)

    def github_app_setup_session_payload(self) -> dict[str, Any]:
        return self._domain.github_app_setup_session_payload()

    def fail_github_app_setup(self, *, message: str, state_value: str) -> None:
        self._domain.fail_github_app_setup(message=message, state_value=state_value)

    def complete_github_app_setup(self, *, code: str, state_value: str) -> dict[str, Any]:
        return self._domain.complete_github_app_setup(code=code, state_value=state_value)

    def disconnect_github_app(self) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_github_app()}

    def list_github_app_installations(self) -> dict[str, Any]:
        return self._domain.list_github_app_installations()

    def connect_github_personal_access_token(self, token: Any, *, host: Any = "") -> dict[str, Any]:
        return {
            "provider": self._domain.connect_github_personal_access_token(
                token,
                host=host,
            )
        }

    def disconnect_github_personal_access_token(self, token_id: str) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_github_personal_access_token(token_id)}

    def disconnect_github_personal_access_tokens(self) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_github_personal_access_tokens()}

    def connect_gitlab_personal_access_token(self, token: Any, *, host: Any = "") -> dict[str, Any]:
        return {
            "provider": self._domain.connect_gitlab_personal_access_token(
                token,
                host=host,
            )
        }

    def disconnect_gitlab_personal_access_token(self, token_id: str) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_gitlab_personal_access_token(token_id)}

    def disconnect_gitlab_personal_access_tokens(self) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_gitlab_personal_access_tokens()}

    def test_openai_chat_title_generation(self, prompt: Any) -> dict[str, Any]:
        return self._domain.test_openai_chat_title_generation(prompt)

    def disconnect_openai_account(self) -> dict[str, Any]:
        return {"provider": self._domain.disconnect_openai_account()}

    def openai_account_session_payload(self) -> dict[str, Any]:
        return self._domain.openai_account_session_payload()

    def start_openai_account_login(self, *, method: str = "browser_callback") -> dict[str, Any]:
        return self._domain.start_openai_account_login(method=method)

    def cancel_openai_account_login(self) -> dict[str, Any]:
        return self._domain.cancel_openai_account_login()

    def _candidate_hosts(
        self,
        *,
        artifact_publish_base_url: str,
        request_host: str,
        request_context: dict[str, Any] | None,
        discover_bridge_hosts: Callable[[], tuple[list[str], dict[str, Any]]],
        normalize_host: Callable[[Any], str],
    ) -> tuple[list[str], dict[str, Any]]:
        del request_host, request_context
        candidate_hosts: list[str] = []

        def add_host(raw_value: Any) -> None:
            normalized_host = normalize_host(raw_value)
            if normalized_host and normalized_host not in candidate_hosts:
                candidate_hosts.append(normalized_host)

        configured_host = (
            urllib.parse.urlsplit(str(artifact_publish_base_url or "")).hostname
            or self.default_artifact_publish_host
        )
        add_host(configured_host)

        bridge_hosts, bridge_diagnostics = discover_bridge_hosts()
        if bridge_hosts:
            add_host(bridge_hosts[0])
        return candidate_hosts, bridge_diagnostics

    def forward_openai_account_callback(
        self,
        *,
        session: Any,
        callback_port: int,
        callback_path: str,
        query: str,
        artifact_publish_base_url: str,
        request_host: str,
        request_context: dict[str, Any] | None,
        discover_bridge_hosts: Callable[[], tuple[list[str], dict[str, Any]]],
        normalize_host: Callable[[Any], str],
        callback_query_summary: Callable[[str], dict[str, Any]],
        redact_url_query_values: Callable[[str], str],
        host_port_netloc: Callable[[str, int], str],
        classify_callback_error: Callable[[BaseException], str],
        logger: Any,
    ) -> AuthCallbackForwardResult:
        callback_query = callback_query_summary(query)
        normalized_context = dict(request_context or {})
        log_extra_base = {
            "component": "auth",
            "operation": "openai_callback_forward",
            "result": "started",
            "chat_id": "",
            "project_id": "",
            "request_id": "",
            "duration_ms": 0,
            "error_class": "",
        }
        candidate_hosts, bridge_diagnostics = self._candidate_hosts(
            artifact_publish_base_url=artifact_publish_base_url,
            request_host=request_host,
            request_context=normalized_context,
            discover_bridge_hosts=discover_bridge_hosts,
            normalize_host=normalize_host,
        )

        logger.info(
            (
                "OpenAI callback forward resolution "
                "session_id=%s container=%s callback_path=%s callback_port=%s "
                "callback_query=%s request_context=%s bridge_routing=%s candidate_hosts=%s"
            ),
            session.id,
            session.container_name,
            callback_path,
            callback_port,
            json.dumps(callback_query, sort_keys=True),
            json.dumps(
                {
                    "client_host": normalized_context.get("client_host") or "",
                    "forwarded_host": normalized_context.get("forwarded_host") or "",
                    "forwarded_proto": normalized_context.get("forwarded_proto") or "",
                    "forwarded_port": normalized_context.get("forwarded_host_port"),
                    "x_forwarded_host": normalized_context.get("x_forwarded_host") or "",
                    "x_forwarded_proto": normalized_context.get("x_forwarded_proto") or "",
                    "x_forwarded_port": normalized_context.get("x_forwarded_port"),
                    "host_header_host": normalized_context.get("host_header_host") or "",
                    "host_header_port": normalized_context.get("host_header_port"),
                },
                sort_keys=True,
            ),
            json.dumps(bridge_diagnostics, sort_keys=True),
            ", ".join(candidate_hosts),
            extra=log_extra_base,
        )

        status_code = 0
        response_body = ""
        target_origin = ""
        last_exc: BaseException | None = None
        failure_categories: list[str] = []
        forwarded_successfully = False

        for candidate_host in candidate_hosts:
            if forwarded_successfully:
                break
            target_url = urllib.parse.urlunparse(
                ("http", host_port_netloc(candidate_host, callback_port), callback_path, "", query, "")
            )
            redacted_target_url = redact_url_query_values(target_url)
            request = urllib.request.Request(target_url, method="GET")
            logger.info(
                "OpenAI callback forward upstream request session_id=%s target=%s timeout_sec=%.1f",
                session.id,
                redacted_target_url,
                self.callback_forward_timeout_seconds,
                extra={**log_extra_base, "result": "request"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.callback_forward_timeout_seconds) as response:
                    status_code = int(response.getcode() or 0)
                    response_body = response.read().decode("utf-8", errors="ignore")
                target_origin = f"http://{host_port_netloc(candidate_host, callback_port)}"
                logger.info(
                    "OpenAI callback forward upstream response session_id=%s target=%s status=%s error_class=none",
                    session.id,
                    redacted_target_url,
                    status_code,
                    extra={**log_extra_base, "result": "success"},
                )
                forwarded_successfully = True
                break
            except urllib.error.HTTPError as exc:
                status_code = int(exc.code or 0)
                response_body = exc.read().decode("utf-8", errors="ignore")
                target_origin = f"http://{host_port_netloc(candidate_host, callback_port)}"
                logger.warning(
                    (
                        "OpenAI callback forward upstream response session_id=%s target=%s "
                        "status=%s error_class=http_error"
                    ),
                    session.id,
                    redacted_target_url,
                    status_code,
                    extra={**log_extra_base, "result": "http_error", "error_class": "http_error"},
                )
                forwarded_successfully = True
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                error_class = classify_callback_error(exc)
                failure_categories.append(error_class)
                logger.warning(
                    (
                        "OpenAI callback forward upstream error session_id=%s target=%s "
                        "error_class=%s error_type=%s detail=%s"
                    ),
                    session.id,
                    redacted_target_url,
                    error_class,
                    type(exc).__name__,
                    str(exc),
                    extra={**log_extra_base, "result": "upstream_error", "error_class": error_class},
                )
                continue

        if not forwarded_successfully:
            attempted = ", ".join(f"http://{host_port_netloc(host, callback_port)}" for host in candidate_hosts)
            failure_reason = "all_upstream_targets_failed"
            if failure_categories:
                failure_reason = "+".join(sorted(set(failure_categories)))
            logger.error(
                (
                    "OpenAI callback forward failed session_id=%s failure_reason=%s "
                    "attempted_origins=%s callback_path=%s callback_query=%s"
                ),
                session.id,
                failure_reason,
                attempted,
                callback_path,
                json.dumps(callback_query, sort_keys=True),
                extra={**log_extra_base, "result": "failed", "error_class": failure_reason},
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Failed to forward OAuth callback to login container. "
                    f"Reason: {failure_reason}. Attempted: {attempted}"
                ),
            ) from last_exc

        return AuthCallbackForwardResult(
            status_code=status_code,
            response_body=response_body,
            target_origin=target_origin,
        )


__all__ = ["AuthService", "AuthCallbackForwardResult"]
