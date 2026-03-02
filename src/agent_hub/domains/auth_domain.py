from __future__ import annotations

from typing import Any


class AuthDomain:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def auth_settings_payload(self) -> dict[str, Any]:
        return self._state.auth_settings_payload()

    def connect_openai(self, api_key: Any, *, verify: bool) -> dict[str, Any]:
        return self._state.connect_openai(api_key, verify=verify)

    def disconnect_openai(self) -> dict[str, Any]:
        return self._state.disconnect_openai()

    def connect_github_app(self, installation_id: Any) -> dict[str, Any]:
        return self._state.connect_github_app(installation_id)

    def start_github_app_setup(self, *, origin: Any) -> dict[str, Any]:
        return self._state.start_github_app_setup(origin=origin)

    def github_app_setup_session_payload(self) -> dict[str, Any]:
        return self._state.github_app_setup_session_payload()

    def fail_github_app_setup(self, *, message: str, state_value: str) -> None:
        self._state.fail_github_app_setup(message=message, state_value=state_value)

    def complete_github_app_setup(self, *, code: str, state_value: str) -> dict[str, Any]:
        return self._state.complete_github_app_setup(code=code, state_value=state_value)

    def disconnect_github_app(self) -> dict[str, Any]:
        return self._state.disconnect_github_app()

    def list_github_app_installations(self) -> dict[str, Any]:
        return self._state.list_github_app_installations()

    def connect_github_personal_access_token(self, token: Any, *, host: Any = "") -> dict[str, Any]:
        return self._state.connect_github_personal_access_token(token, host=host)

    def disconnect_github_personal_access_token(self, token_id: str) -> dict[str, Any]:
        return self._state.disconnect_github_personal_access_token(token_id)

    def disconnect_github_personal_access_tokens(self) -> dict[str, Any]:
        return self._state.disconnect_github_personal_access_tokens()

    def connect_gitlab_personal_access_token(self, token: Any, *, host: Any = "") -> dict[str, Any]:
        return self._state.connect_gitlab_personal_access_token(token, host=host)

    def disconnect_gitlab_personal_access_token(self, token_id: str) -> dict[str, Any]:
        return self._state.disconnect_gitlab_personal_access_token(token_id)

    def disconnect_gitlab_personal_access_tokens(self) -> dict[str, Any]:
        return self._state.disconnect_gitlab_personal_access_tokens()

    def test_openai_chat_title_generation(self, prompt: Any) -> dict[str, Any]:
        return self._state.test_openai_chat_title_generation(prompt)

    def disconnect_openai_account(self) -> dict[str, Any]:
        return self._state.disconnect_openai_account()

    def openai_account_session_payload(self) -> dict[str, Any]:
        return self._state.openai_account_session_payload()

    def start_openai_account_login(self, *, method: str = "browser_callback") -> dict[str, Any]:
        return self._state.start_openai_account_login(method=method)

    def cancel_openai_account_login(self) -> dict[str, Any]:
        return self._state.cancel_openai_account_login()

