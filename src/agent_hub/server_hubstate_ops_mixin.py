from __future__ import annotations

# Import HubState runtime globals defined in server.py before mixin import.
import agent_hub.server as _hub_server

globals().update(_hub_server.__dict__)


class HubStateOpsMixin:
    def _reload_github_app_settings(self) -> None:
        env_settings, env_error = _load_github_app_settings_from_env()
        if env_settings is not None or env_error:
            self.github_app_settings = env_settings
            self.github_app_settings_error = env_error
            return

        file_settings, file_error = _load_github_app_settings_from_file(self.github_app_settings_file)
        self.github_app_settings = file_settings
        self.github_app_settings_error = file_error

    def _github_setup_base_urls(self) -> tuple[str, str]:
        if self.github_app_settings is not None:
            return self.github_app_settings.web_base_url, self.github_app_settings.api_base_url

        web_base_raw = str(os.environ.get(GITHUB_APP_WEB_BASE_URL_ENV, GITHUB_APP_DEFAULT_WEB_BASE_URL)).strip()
        api_base_raw = str(os.environ.get(GITHUB_APP_API_BASE_URL_ENV, GITHUB_APP_DEFAULT_API_BASE_URL)).strip()
        try:
            web_base = _normalize_absolute_http_base_url(web_base_raw, GITHUB_APP_WEB_BASE_URL_ENV)
            api_base = _normalize_absolute_http_base_url(api_base_raw, GITHUB_APP_API_BASE_URL_ENV)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return web_base, api_base

    @staticmethod
    def _github_setup_session_is_active(status: str) -> bool:
        return status in {"awaiting_user", "converting"}

    @staticmethod
    def _github_setup_session_is_expired(expires_at: str) -> bool:
        expires_unix = _iso_to_unix_seconds(expires_at)
        return expires_unix > 0 and int(time.time()) >= expires_unix

    def _github_setup_session_locked(self) -> GithubAppSetupSession | None:
        session = self._github_setup_session
        if session is None:
            return None
        if (
            self._github_setup_session_is_active(session.status)
            and self._github_setup_session_is_expired(session.expires_at)
        ):
            session.status = "expired"
            session.completed_at = session.completed_at or _iso_now()
            if not session.error:
                session.error = "GitHub setup session expired. Click Connect to GitHub and try again."
        return session

    def _github_setup_session_payload_locked(self) -> dict[str, Any]:
        session = self._github_setup_session_locked()
        if session is None:
            return {
                "active": False,
                "id": "",
                "status": "idle",
                "form_action": "",
                "manifest": {},
                "started_at": "",
                "expires_at": "",
                "completed_at": "",
                "error": "",
                "app_id": "",
                "app_slug": "",
                "callback_url": "",
            }
        return {
            "active": self._github_setup_session_is_active(session.status),
            "id": session.id,
            "status": session.status,
            "form_action": session.form_action,
            "manifest": dict(session.manifest),
            "started_at": session.started_at,
            "expires_at": session.expires_at,
            "completed_at": session.completed_at,
            "error": session.error,
            "app_id": session.app_id,
            "app_slug": session.app_slug,
            "callback_url": session.callback_url,
        }

    def github_app_setup_session_payload(self) -> dict[str, Any]:
        with self._github_setup_lock:
            return self._github_setup_session_payload_locked()

    def start_github_app_setup(self, origin: Any) -> dict[str, Any]:
        if _github_app_env_config_present():
            raise HTTPException(
                status_code=400,
                detail=(
                    "GitHub App setup from Settings is disabled while AGENT_HUB_GITHUB_APP_* environment variables are set."
                ),
            )

        origin_text = str(origin or "").strip()
        if not origin_text:
            raise HTTPException(status_code=400, detail="origin is required.")
        try:
            normalized_origin = _normalize_absolute_http_base_url(origin_text, "origin")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        parsed_origin = urllib.parse.urlsplit(normalized_origin)
        callback_url = urllib.parse.urlunsplit(
            (parsed_origin.scheme, parsed_origin.netloc, "/api/settings/auth/github-app/setup/callback", "", "")
        )
        web_base_url, api_base_url = self._github_setup_base_urls()
        setup_state = secrets.token_urlsafe(24)
        form_action = f"{web_base_url}/settings/apps/new?state={urllib.parse.quote(setup_state, safe='')}"
        app_name = f"{GITHUB_APP_DEFAULT_NAME}-{secrets.token_hex(2)}"
        manifest = {
            "name": app_name,
            "url": normalized_origin,
            "redirect_url": callback_url,
            "callback_urls": [callback_url],
            "public": False,
            "request_oauth_on_install": False,
            "hook_attributes": {
                "url": callback_url,
                "active": False,
            },
            "default_permissions": {
                "contents": "write",
                "pull_requests": "write",
                "issues": "write",
            },
            "default_events": [],
        }
        now = time.time()
        with self._github_setup_lock:
            self._github_setup_session = GithubAppSetupSession(
                id=uuid.uuid4().hex,
                state=setup_state,
                status="awaiting_user",
                form_action=form_action,
                manifest=manifest,
                callback_url=callback_url,
                web_base_url=web_base_url,
                api_base_url=api_base_url,
                started_at=_iso_from_timestamp(now),
                expires_at=_iso_from_timestamp(now + GITHUB_APP_SETUP_SESSION_LIFETIME_SECONDS),
            )
            return self._github_setup_session_payload_locked()

    def _github_manifest_conversion_request(self, api_base_url: str, code: str) -> dict[str, Any]:
        path_code = urllib.parse.quote(str(code or "").strip(), safe="")
        request = urllib.request.Request(
            f"{api_base_url}/app-manifests/{path_code}/conversions",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "agent-hub",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=GITHUB_APP_API_TIMEOUT_SECONDS) as response:
                status = int(response.getcode() or 0)
                body_text = response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            status = int(exc.code or 0)
            body_text = exc.read().decode("utf-8", errors="ignore")
            message = _github_api_error_message(body_text)
            detail = f"GitHub app setup conversion failed with status {status}."
            if message:
                detail = f"{detail} {message}"
            raise HTTPException(status_code=400 if status < 500 else 502, detail=detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HTTPException(
                status_code=502,
                detail="GitHub app setup conversion failed due to a network error.",
            ) from exc

        if not (200 <= status < 300):
            message = _github_api_error_message(body_text)
            detail = f"GitHub app setup conversion failed with status {status}."
            if message:
                detail = f"{detail} {message}"
            raise HTTPException(status_code=400 if status < 500 else 502, detail=detail)

        try:
            payload = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="GitHub returned invalid app setup conversion data.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="GitHub returned invalid app setup conversion data.")
        return payload

    def _clear_materialized_git_credentials(self) -> None:
        if not self.git_credentials_dir.exists():
            return
        for path in self.git_credentials_dir.iterdir():
            if not path.is_file():
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to clear materialized git credentials.") from exc

    def _clear_github_installation_state(self, remove_credentials: bool = True) -> None:
        paths = [self.github_app_installation_file]
        for path in paths:
            if not path.exists():
                continue
            try:
                path.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to clear previous GitHub installation state.") from exc
        if remove_credentials:
            self._clear_materialized_git_credentials()
        with self._github_token_lock:
            self._github_token_cache = {}

    def _clear_personal_access_token_state(self, provider: str, remove_credentials: bool = True) -> None:
        token_file = self._token_store_file_for_provider(provider)
        if token_file.exists():
            try:
                token_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to clear stored personal access token credentials.") from exc
        if remove_credentials:
            self._clear_materialized_git_credentials()

    def _persist_github_app_settings(self, settings: GithubAppSettings) -> None:
        payload = {
            "app_id": settings.app_id,
            "app_slug": settings.app_slug,
            "private_key": settings.private_key,
            "web_base_url": settings.web_base_url,
            "api_base_url": settings.api_base_url,
            "configured_at": _iso_now(),
        }
        _write_private_env_file(self.github_app_settings_file, json.dumps(payload, indent=2) + "\n")
        self.github_app_settings = settings
        self.github_app_settings_error = ""
        with self._github_token_lock:
            self._github_token_cache = {}

    def complete_github_app_setup(self, code: Any, state_value: Any) -> dict[str, Any]:
        code_text = str(code or "").strip()
        if not code_text:
            raise HTTPException(status_code=400, detail="Missing GitHub setup code.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", code_text):
            raise HTTPException(status_code=400, detail="Invalid GitHub setup code.")

        state_text = str(state_value or "").strip()
        if not state_text:
            raise HTTPException(status_code=400, detail="Missing GitHub setup state.")

        with self._github_setup_lock:
            session = self._github_setup_session_locked()
            if session is None:
                raise HTTPException(status_code=400, detail="No GitHub setup session is active.")
            if session.status == "completed":
                return self._github_setup_session_payload_locked()
            if session.status in {"failed", "expired"}:
                detail = session.error or "GitHub setup session is not active."
                raise HTTPException(status_code=400, detail=detail)
            if not hmac.compare_digest(session.state, state_text):
                session.status = "failed"
                session.completed_at = _iso_now()
                session.error = "GitHub setup state did not match. Start setup again from Settings."
                raise HTTPException(status_code=400, detail=session.error)
            session.status = "converting"
            session.error = ""
            api_base_url = session.api_base_url
            web_base_url = session.web_base_url

        try:
            conversion_payload = self._github_manifest_conversion_request(api_base_url, code_text)
            resolved_settings = _normalize_github_app_settings_payload(
                {
                    "app_id": conversion_payload.get("id"),
                    "app_slug": conversion_payload.get("slug"),
                    "private_key": conversion_payload.get("pem"),
                    "web_base_url": web_base_url,
                    "api_base_url": api_base_url,
                },
                "GitHub app setup conversion",
            )
            self._persist_github_app_settings(resolved_settings)
            self._clear_github_installation_state(remove_credentials=False)
        except ValueError as exc:
            with self._github_setup_lock:
                session = self._github_setup_session_locked()
                if session is not None:
                    session.status = "failed"
                    session.completed_at = _iso_now()
                    session.error = str(exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except HTTPException as exc:
            with self._github_setup_lock:
                session = self._github_setup_session_locked()
                if session is not None and session.status != "completed":
                    session.status = "failed"
                    session.completed_at = _iso_now()
                    session.error = str(exc.detail or "GitHub app setup failed.")
            raise

        with self._github_setup_lock:
            session = self._github_setup_session_locked()
            if session is not None:
                session.status = "completed"
                session.completed_at = _iso_now()
                session.error = ""
                session.app_id = resolved_settings.app_id
                session.app_slug = resolved_settings.app_slug
            payload = self._github_setup_session_payload_locked()

        self._emit_auth_changed(reason="github_app_configured")
        return payload

    def fail_github_app_setup(self, message: Any, state_value: Any = "") -> dict[str, Any]:
        detail = str(message or "").strip() or "GitHub app setup failed."
        state_text = str(state_value or "").strip()
        with self._github_setup_lock:
            session = self._github_setup_session_locked()
            if session is None:
                return self._github_setup_session_payload_locked()
            if state_text and not hmac.compare_digest(session.state, state_text):
                return self._github_setup_session_payload_locked()
            session.status = "failed"
            session.completed_at = _iso_now()
            session.error = detail
            return self._github_setup_session_payload_locked()

    def _github_provider_host(self) -> str:
        if self.github_app_settings is None:
            return "github.com"
        parsed = urllib.parse.urlsplit(self.github_app_settings.web_base_url)
        return (parsed.hostname or "github.com").lower()

    def _github_install_url(self) -> str:
        if self.github_app_settings is None:
            return ""
        return f"{self.github_app_settings.web_base_url}/apps/{self.github_app_settings.app_slug}/installations/new"

    def _github_connected_installation(self) -> dict[str, Any] | None:
        payload = _read_json_if_exists(self.github_app_installation_file)
        if payload is None:
            return None
        installation_id = payload.get("installation_id")
        if isinstance(installation_id, int) and installation_id > 0:
            payload["installation_id"] = installation_id
            return payload
        return None

    def _token_store_file_for_provider(self, provider: str) -> Path:
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider == GIT_PROVIDER_GITLAB:
            return self.gitlab_tokens_file
        return self.github_tokens_file

    def _normalize_personal_access_token_record(
        self,
        raw_record: dict[str, Any],
        *,
        default_host: str,
        default_provider: str,
        record_index: int,
    ) -> dict[str, Any]:
        token = str(raw_record.get("personal_access_token") or "").strip()
        account_login = str(raw_record.get("account_login") or "").strip()
        if not token or not account_login:
            raise CredentialResolutionError(
                "Invalid persisted personal access token record: "
                f"provider={default_provider} index={record_index} requires personal_access_token and account_login."
            )

        provider = str(raw_record.get("provider") or default_provider).strip().lower()
        if provider not in {GIT_PROVIDER_GITHUB, GIT_PROVIDER_GITLAB}:
            raise CredentialResolutionError(
                "Invalid persisted personal access token record: "
                f"provider={provider!r} index={record_index} is unsupported."
            )

        host_value = raw_record.get("host") or default_host
        default_scheme = (
            str(raw_record.get("scheme") or GIT_CREDENTIAL_DEFAULT_SCHEME).strip()
            or GIT_CREDENTIAL_DEFAULT_SCHEME
        )
        try:
            scheme, host = _normalize_github_credential_endpoint(
                host_value,
                field_name="host",
                default_scheme=default_scheme,
            )
        except HTTPException as exc:
            raise CredentialResolutionError(
                "Invalid persisted personal access token record endpoint: "
                f"provider={provider} index={record_index}."
            ) from exc

        account_name = str(raw_record.get("account_name") or account_login).strip() or account_login
        account_email = str(raw_record.get("account_email") or "").strip()
        host_name, _port = _split_host_port(host)
        if not account_email:
            if provider == GIT_PROVIDER_GITLAB:
                account_email = f"{account_login}@users.noreply.{host_name or 'gitlab.com'}"
            else:
                account_email = f"{account_login}@users.noreply.github.com"

        git_user_name = str(raw_record.get("git_user_name") or account_name).strip() or account_name
        git_user_email = str(raw_record.get("git_user_email") or account_email).strip() or account_email
        account_id = str(raw_record.get("account_id") or "").strip()
        token_scopes = str(raw_record.get("token_scopes") or "").strip()
        verified_at = str(raw_record.get("verified_at") or "").strip()
        connected_at = str(raw_record.get("connected_at") or "").strip()

        token_id = str(raw_record.get("token_id") or raw_record.get("id") or "").strip()
        if token_id:
            token_id = token_id[:GITHUB_PERSONAL_ACCESS_TOKEN_ID_MAX_CHARS]
        if not token_id:
            token_seed = f"{provider}|{host}|{account_login.lower()}|{record_index}"
            token_id = hashlib.sha256(token_seed.encode("utf-8")).hexdigest()[:32]

        return {
            "token_id": token_id,
            "provider": provider,
            "host": host,
            "scheme": scheme,
            "personal_access_token": token,
            "account_login": account_login,
            "account_name": account_name,
            "account_email": account_email,
            "account_id": account_id,
            "git_user_name": git_user_name,
            "git_user_email": git_user_email,
            "token_scopes": token_scopes,
            "verified_at": verified_at,
            "connected_at": connected_at,
        }

    def _connected_personal_access_tokens(self, provider: str = "") -> list[dict[str, Any]]:
        providers: list[str]
        normalized_provider = str(provider or "").strip().lower()
        if normalized_provider in {GIT_PROVIDER_GITHUB, GIT_PROVIDER_GITLAB}:
            providers = [normalized_provider]
        else:
            providers = [GIT_PROVIDER_GITHUB, GIT_PROVIDER_GITLAB]

        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for provider_name in providers:
            token_file = self._token_store_file_for_provider(provider_name)
            payload = _read_json_if_exists(token_file)
            if payload is None:
                continue
            raw_records: list[dict[str, Any]] = []
            if isinstance(payload.get("tokens"), list):
                raw_records = [item for item in payload["tokens"] if isinstance(item, dict)]
            elif isinstance(payload, dict):
                raw_records = [payload]
            default_host = self._github_provider_host() if provider_name == GIT_PROVIDER_GITHUB else "gitlab.com"
            for index, raw_record in enumerate(raw_records):
                normalized = self._normalize_personal_access_token_record(
                    raw_record,
                    default_host=default_host,
                    default_provider=provider_name,
                    record_index=index,
                )
                token_id = str(normalized.get("token_id") or "").strip()
                if token_id in seen_ids:
                    token_id = hashlib.sha256(f"{token_id}|{provider_name}|{index}".encode("utf-8")).hexdigest()[:32]
                    normalized["token_id"] = token_id
                seen_ids.add(token_id)
                records.append(normalized)
        return records

    def _persist_personal_access_tokens(self, records: list[dict[str, Any]], provider: str) -> None:
        normalized_provider = (
            GIT_PROVIDER_GITLAB if str(provider or "").strip().lower() == GIT_PROVIDER_GITLAB else GIT_PROVIDER_GITHUB
        )
        token_file = self._token_store_file_for_provider(normalized_provider)
        provider_records = [
            record
            for record in records
            if str(record.get("provider") or "").strip().lower() == normalized_provider
        ]
        if not provider_records:
            if token_file.exists():
                try:
                    token_file.unlink()
                except OSError as exc:
                    raise HTTPException(status_code=500, detail="Failed to clear stored personal access token credentials.") from exc
            return

        payload_records: list[dict[str, Any]] = []
        for record in provider_records:
            payload_records.append(
                {
                    "token_id": str(record.get("token_id") or "").strip(),
                    "provider": normalized_provider,
                    "host": str(record.get("host") or "").strip(),
                    "scheme": _normalize_github_credential_scheme(record.get("scheme"), field_name="scheme"),
                    "personal_access_token": str(record.get("personal_access_token") or "").strip(),
                    "account_login": str(record.get("account_login") or "").strip(),
                    "account_name": str(record.get("account_name") or "").strip(),
                    "account_email": str(record.get("account_email") or "").strip(),
                    "account_id": str(record.get("account_id") or "").strip(),
                    "git_user_name": str(record.get("git_user_name") or "").strip(),
                    "git_user_email": str(record.get("git_user_email") or "").strip(),
                    "token_scopes": str(record.get("token_scopes") or "").strip(),
                    "verified_at": str(record.get("verified_at") or "").strip(),
                    "connected_at": str(record.get("connected_at") or "").strip(),
                }
            )
        payload = {"tokens": payload_records, "updated_at": _iso_now()}
        _write_private_env_file(token_file, json.dumps(payload, indent=2) + "\n")

    @staticmethod
    def _connected_at_sort_key(record: dict[str, Any]) -> tuple[str, str]:
        connected_at = str(record.get("connected_at") or "").strip()
        token_id = str(record.get("token_id") or "").strip()
        return connected_at, token_id

    def _personal_access_tokens_for_repo(
        self,
        repo_url: str,
        credential_binding: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        repo_host = _git_repo_host(repo_url)
        if not repo_host:
            return []
        repo_scheme = _git_repo_scheme(repo_url)
        matching_host = [
            token
            for token in self._connected_personal_access_tokens()
            if str(token.get("host") or "").strip().lower() == repo_host
        ]
        if not matching_host:
            return []
        if repo_scheme in GIT_CREDENTIAL_ALLOWED_SCHEMES:
            matching_scheme = [
                token
                for token in matching_host
                if str(token.get("scheme") or GIT_CREDENTIAL_DEFAULT_SCHEME).strip().lower() == repo_scheme
            ]
            if matching_scheme:
                matching_host = matching_scheme

        tokens: list[dict[str, Any]] = []
        seen_token_ids: set[str] = set()

        normalized_binding = _normalize_project_credential_binding(credential_binding)
        if normalized_binding["mode"] in {
            PROJECT_CREDENTIAL_BINDING_MODE_SET,
            PROJECT_CREDENTIAL_BINDING_MODE_SINGLE,
        }:
            preferred_ids = normalized_binding["credential_ids"]
            if preferred_ids:
                by_id = {str(token.get("token_id") or "").strip(): token for token in matching_host}
                for token_id in preferred_ids:
                    if token_id in by_id and token_id not in seen_token_ids:
                        tokens.append(by_id[token_id])
                        seen_token_ids.add(token_id)
                if normalized_binding["mode"] == PROJECT_CREDENTIAL_BINDING_MODE_SINGLE and tokens:
                    return tokens

        # Add remaining matches, ordered by most recent first
        ordered_matches = list(enumerate(matching_host))
        ordered_matches.sort(
            key=lambda item: (str(item[1].get("connected_at") or "").strip(), -item[0]),
            reverse=True,
        )
        for _, token in ordered_matches:
            token_id = str(token.get("token_id") or "").strip()
            if token_id not in seen_token_ids:
                tokens.append(token)
                seen_token_ids.add(token_id)

        return tokens

    def _personal_access_token_for_repo(
        self,
        repo_url: str,
        credential_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        tokens = self._personal_access_tokens_for_repo(repo_url, credential_binding=credential_binding)
        return tokens[0] if tokens else None

    def _github_personal_access_token_for_repo(
        self,
        repo_url: str,
        credential_binding: dict[str, Any] | None = None,
    ) -> str:
        token_record = self._personal_access_token_for_repo(repo_url, credential_binding=credential_binding)
        if (
            token_record is None
            or str(token_record.get("provider") or "").strip().lower() != GIT_PROVIDER_GITHUB
        ):
            return ""
        return str(token_record.get("personal_access_token") or "").strip()

    def _recommended_auth_env_vars_for_repo(
        self,
        repo_url: str,
        credential_binding: dict[str, Any] | None = None,
    ) -> list[str]:
        token_record = self._personal_access_token_for_repo(
            repo_url,
            credential_binding=credential_binding,
        )
        if not token_record:
            return []
        token = str(token_record.get("personal_access_token") or "").strip()
        if not token:
            return []
        provider = str(token_record.get("provider") or "").strip().lower()
        if provider == GIT_PROVIDER_GITLAB:
            return [f"GITLAB_TOKEN={token}"]
        if provider == GIT_PROVIDER_GITHUB:
            # Keep both in sync so git/gh workflows work without extra setup.
            return [
                f"GITHUB_TOKEN={token}",
                f"GH_TOKEN={token}",
            ]
        return []

    def _github_connected_personal_access_tokens(self) -> list[dict[str, Any]]:
        return self._connected_personal_access_tokens(GIT_PROVIDER_GITHUB)

    def _gitlab_connected_personal_access_tokens(self) -> list[dict[str, Any]]:
        return self._connected_personal_access_tokens(GIT_PROVIDER_GITLAB)

    def _github_api_base_url_for_host(self, host: str, scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME) -> str:
        normalized_scheme = _normalize_github_credential_scheme(scheme, field_name="scheme")
        normalized_host = _normalize_github_credential_host(host, field_name="host")
        if (
            normalized_scheme == "https"
            and self.github_app_settings is not None
            and self._github_provider_host() == normalized_host
        ):
            return self.github_app_settings.api_base_url
        if normalized_scheme == "https" and normalized_host == "github.com":
            return GITHUB_APP_DEFAULT_API_BASE_URL
        if normalized_scheme != "https":
            return f"{normalized_scheme}://{normalized_host}/api/v3"
        return f"https://{normalized_host}/api/v3"

    @staticmethod
    def _gitlab_api_base_url_for_host(host: str, scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME) -> str:
        normalized_scheme = _normalize_github_credential_scheme(scheme, field_name="scheme")
        normalized_host = _normalize_github_credential_host(host, field_name="host")
        return f"{normalized_scheme}://{normalized_host}/api/v4"

    @staticmethod
    def _pat_verification_request(
        request: urllib.request.Request,
        provider_label: str,
    ) -> tuple[int, str, dict[str, str]]:
        try:
            with urllib.request.urlopen(request, timeout=GITHUB_APP_API_TIMEOUT_SECONDS) as response:
                status = int(response.getcode() or 0)
                payload_text = response.read().decode("utf-8", errors="ignore")
                response_headers = {str(key): str(value) for key, value in response.headers.items()}
                return status, payload_text, response_headers
        except urllib.error.HTTPError as exc:
            status = int(exc.code or 0)
            payload_text = exc.read().decode("utf-8", errors="ignore")
            response_headers = {str(key): str(value) for key, value in (exc.headers.items() if exc.headers else [])}
            return status, payload_text, response_headers
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HTTPException(
                status_code=502,
                detail=f"{provider_label} personal access token verification failed due to a network error.",
            ) from exc

    @staticmethod
    def _header_value(headers: dict[str, str], *keys: str) -> str:
        if not headers:
            return ""
        for key in keys:
            for header_name, value in headers.items():
                if header_name.lower() == key.lower():
                    return str(value or "").strip()
        return ""

    @staticmethod
    def _token_scope_set(raw_scopes: Any) -> set[str]:
        if raw_scopes is None:
            return set()
        text = str(raw_scopes).strip().lower()
        if not text:
            return set()
        return {token.strip() for token in re.split(r"[\s,]+", text) if token.strip()}

    @classmethod
    def _validate_gitlab_personal_access_token_scopes(cls, token_scopes: Any) -> None:
        scope_set = cls._token_scope_set(token_scopes)
        if not scope_set:
            return
        if "api" in scope_set:
            return
        missing_scopes = sorted(GITLAB_PERSONAL_ACCESS_TOKEN_REQUIRED_SCOPES.difference(scope_set))
        if not missing_scopes:
            return
        missing_text = ", ".join(missing_scopes)
        raise HTTPException(
            status_code=400,
            detail=(
                "GitLab personal access token is missing required scopes: "
                f"{missing_text}. Provide `api` or both `read_repository` and `write_repository`."
            ),
        )

    def _verify_github_personal_access_token(self, token: str, host: str, scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME) -> dict[str, str]:
        normalized_host = _normalize_github_credential_host(host, field_name="host")
        normalized_scheme = _normalize_github_credential_scheme(scheme, field_name="scheme")
        host_name, _port = _split_host_port(normalized_host)
        preferred_provider = GIT_PROVIDER_GITLAB if "gitlab" in host_name else GIT_PROVIDER_GITHUB
        providers = (
            [GIT_PROVIDER_GITLAB, GIT_PROVIDER_GITHUB]
            if preferred_provider == GIT_PROVIDER_GITLAB
            else [GIT_PROVIDER_GITHUB, GIT_PROVIDER_GITLAB]
        )

        failures: list[tuple[str, int, str]] = []
        for provider in providers:
            if provider == GIT_PROVIDER_GITHUB:
                api_base_url = self._github_api_base_url_for_host(normalized_host, normalized_scheme)
                request = urllib.request.Request(
                    f"{api_base_url}/user",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "agent-hub",
                        "Authorization": f"Bearer {token}",
                    },
                    method="GET",
                )
                provider_label = "GitHub"
            else:
                api_base_url = self._gitlab_api_base_url_for_host(normalized_host, normalized_scheme)
                request = urllib.request.Request(
                    f"{api_base_url}/user",
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "agent-hub",
                        "Authorization": f"Bearer {token}",
                        "PRIVATE-TOKEN": token,
                    },
                    method="GET",
                )
                provider_label = "GitLab"

            status, payload_text, response_headers = self._pat_verification_request(request, provider_label)
            if 200 <= status < 300:
                try:
                    payload = json.loads(payload_text) if payload_text else {}
                except json.JSONDecodeError as exc:
                    failures.append((provider_label, 502, "returned invalid PAT verification payload."))
                    continue
                if not isinstance(payload, dict):
                    failures.append((provider_label, 502, "returned invalid PAT verification payload."))
                    continue

                if provider == GIT_PROVIDER_GITHUB:
                    account_login = str(payload.get("login") or "").strip()
                    account_name = str(payload.get("name") or "").strip()
                    raw_account_id = payload.get("id")
                    account_email = str(payload.get("email") or "").strip()
                    token_scopes = self._header_value(response_headers, "X-OAuth-Scopes")
                    if not account_login:
                        failures.append(("GitHub", 502, "did not return a user login for this token."))
                        continue
                    account_id = 0
                    if isinstance(raw_account_id, int) and raw_account_id > 0:
                        account_id = raw_account_id
                    elif isinstance(raw_account_id, str) and raw_account_id.isdigit():
                        account_id = int(raw_account_id)
                    if not account_email:
                        if account_id > 0:
                            account_email = f"{account_id}+{account_login}@users.noreply.github.com"
                        else:
                            account_email = f"{account_login}@users.noreply.github.com"
                    return {
                        "provider": GIT_PROVIDER_GITHUB,
                        "account_login": account_login,
                        "account_name": account_name or account_login,
                        "account_email": account_email,
                        "account_id": str(account_id) if account_id > 0 else "",
                        "token_scopes": token_scopes,
                    }

                account_login = str(payload.get("username") or payload.get("login") or "").strip()
                account_name = str(payload.get("name") or "").strip()
                account_email = str(payload.get("email") or "").strip()
                raw_account_id = payload.get("id")
                if not account_login:
                    failures.append(("GitLab", 502, "did not return a user login for this token."))
                    continue
                account_id = 0
                if isinstance(raw_account_id, int) and raw_account_id > 0:
                    account_id = raw_account_id
                elif isinstance(raw_account_id, str) and raw_account_id.isdigit():
                    account_id = int(raw_account_id)
                if not account_email:
                    account_email = f"{account_login}@users.noreply.{host_name or 'gitlab.com'}"
                token_scopes = self._header_value(
                    response_headers,
                    "X-Gitlab-Scopes",
                    "X-GitLab-Scopes",
                    "X-OAuth-Scopes",
                    "X-Oauth-Scopes",
                )
                self._validate_gitlab_personal_access_token_scopes(token_scopes)
                return {
                    "provider": GIT_PROVIDER_GITLAB,
                    "account_login": account_login,
                    "account_name": account_name or account_login,
                    "account_email": account_email,
                    "account_id": str(account_id) if account_id > 0 else "",
                    "token_scopes": token_scopes,
                }

            message = _github_api_error_message(payload_text)
            failures.append((provider_label, status, message))

        unauthorized_failures = [failure for failure in failures if failure[1] in {401, 403}]
        if unauthorized_failures:
            provider_label, status, message = unauthorized_failures[0]
            detail = f"{provider_label} personal access token verification failed with status {status}."
            if message:
                detail = f"{detail} {message}"
            raise HTTPException(status_code=400, detail=detail)

        if failures:
            provider_label, status, message = failures[0]
            detail = f"{provider_label} personal access token verification failed with status {status}."
            if message:
                detail = f"{detail} {message}"
            raise HTTPException(status_code=502, detail=detail)

        raise HTTPException(status_code=502, detail="Git provider personal access token verification failed.")

    def _github_api_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        auth_mode: str = "app",
        token: str = "",
    ) -> tuple[int, str]:
        settings = self.github_app_settings
        if settings is None:
            raise HTTPException(status_code=400, detail="GitHub App is not configured on this server.")
        url = f"{settings.api_base_url}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agent-hub",
        }
        if auth_mode == "app":
            headers["Authorization"] = f"Bearer {_github_app_jwt(settings, self.secrets_dir / 'tmp')}"
        elif auth_mode == "installation":
            resolved_token = str(token or "").strip()
            if not resolved_token:
                raise HTTPException(status_code=500, detail="Missing GitHub installation token.")
            headers["Authorization"] = f"Bearer {resolved_token}"
        else:
            raise HTTPException(status_code=500, detail=f"Unsupported GitHub auth mode: {auth_mode}")

        raw_data = None
        if body is not None:
            raw_data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=raw_data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=GITHUB_APP_API_TIMEOUT_SECONDS) as response:
                status = int(response.getcode() or 0)
                payload_text = response.read().decode("utf-8", errors="ignore")
        except urllib.error.HTTPError as exc:
            status = int(exc.code or 0)
            payload_text = exc.read().decode("utf-8", errors="ignore")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HTTPException(status_code=502, detail="GitHub API request failed due to a network error.") from exc

        if 200 <= status < 300:
            return status, payload_text

        detail = f"GitHub API request failed with status {status}."
        message = _github_api_error_message(payload_text)
        if message:
            detail = f"{detail} {message}"
        raise HTTPException(status_code=502, detail=detail)

    def _github_installation_token(self, installation_id: int, force_refresh: bool = False) -> tuple[str, str]:
        now = int(time.time())
        with self._github_token_lock:
            cached_installation_id = int(self._github_token_cache.get("installation_id") or 0)
            cached_token = str(self._github_token_cache.get("token") or "")
            cached_expires_at = str(self._github_token_cache.get("expires_at") or "")
            expires_unix = _iso_to_unix_seconds(cached_expires_at)
            if (
                not force_refresh
                and cached_installation_id == installation_id
                and cached_token
                and expires_unix > now + GITHUB_APP_TOKEN_REFRESH_SKEW_SECONDS
            ):
                return cached_token, cached_expires_at

        _status, payload_text = self._github_api_request(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            body={},
            auth_mode="app",
        )
        try:
            payload = json.loads(payload_text) if payload_text else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation token payload.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation token payload.")

        token = str(payload.get("token") or "").strip()
        expires_at = str(payload.get("expires_at") or "").strip()
        if not token or not expires_at:
            raise HTTPException(status_code=502, detail="GitHub API did not return a valid installation token.")

        with self._github_token_lock:
            self._github_token_cache = {
                "installation_id": installation_id,
                "token": token,
                "expires_at": expires_at,
            }
        return token, expires_at

    def _materialized_credential_file_path(self, context_key: str, credential_id: str) -> Path:
        context = str(context_key or "").strip() or "default"
        token = str(credential_id or "").strip() or "credential"
        digest = hashlib.sha256(f"{context}|{token}".encode("utf-8")).hexdigest()[:24]
        return self.git_credentials_dir / f"{digest}.git-credentials"

    def _refresh_github_git_credentials(self, installation_id: int, host: str, context_key: str = "") -> str:
        token, _expires_at = self._github_installation_token(installation_id)
        return self._write_github_git_credentials(
            host=host,
            username="x-access-token",
            secret=token,
            scheme=GIT_CREDENTIAL_DEFAULT_SCHEME,
            credential_id=f"github_app:{installation_id}",
            context_key=context_key,
        )

    def _write_github_git_credentials(
        self,
        host: str,
        username: str,
        secret: str,
        scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME,
        credential_id: str = "",
        context_key: str = "",
    ) -> str:
        normalized_scheme = _normalize_github_credential_scheme(scheme, field_name="scheme")
        normalized_host = _normalize_github_credential_host(host, field_name="host")
        resolved_username = str(username or "").strip()
        resolved_secret = str(secret or "").strip()
        if not resolved_username:
            raise HTTPException(status_code=500, detail="Missing GitHub credential username.")
        if not resolved_secret:
            raise HTTPException(status_code=500, detail="Missing GitHub credential secret.")
        encoded_username = urllib.parse.quote(resolved_username, safe="")
        encoded_secret = urllib.parse.quote(resolved_secret, safe="")
        resolved_credential_id = str(credential_id or "").strip() or f"{normalized_host}:{resolved_username}"
        output_file = self._materialized_credential_file_path(context_key, resolved_credential_id)
        _write_private_env_file(
            output_file,
            f"{normalized_scheme}://{encoded_username}:{encoded_secret}@{normalized_host}\n",
        )
        return str(output_file)

    def _refresh_github_git_credentials_for_personal_access_token(
        self,
        token: str,
        host: str,
        account_login: str,
        scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME,
        context_key: str = "",
        credential_id: str = "",
    ) -> str:
        return self._write_github_git_credentials(
            host=host,
            username=account_login,
            secret=token,
            scheme=scheme,
            credential_id=credential_id,
            context_key=context_key,
        )

    @staticmethod
    def _git_env_for_credentials_file(
        credential_file: str,
        host: str,
        scheme: str = GIT_CREDENTIAL_DEFAULT_SCHEME,
    ) -> dict[str, str]:
        normalized_scheme = _normalize_github_credential_scheme(scheme, field_name="scheme")
        normalized_host = str(host or "github.com").strip().lower()
        host_name, _port = _split_host_port(normalized_host)
        normalized_ssh_host = host_name or normalized_host
        git_prefix = f"{normalized_scheme}://{normalized_host}/"
        
        # Ensure we use an absolute path for the credential file
        abs_cred_file = str(Path(credential_file).resolve())
        
        return {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": f"store --file={abs_cred_file}",
            "GIT_CONFIG_KEY_1": f"url.{git_prefix}.insteadOf",
            "GIT_CONFIG_VALUE_1": f"git@{normalized_ssh_host}:",
            "GIT_CONFIG_KEY_2": f"url.{git_prefix}.insteadOf",
            "GIT_CONFIG_VALUE_2": f"ssh://git@{normalized_ssh_host}/",
        }

    def _github_repo_all_auth_contexts(
        self,
        repo_url: str,
        project: dict[str, Any] | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        repo_host = _git_repo_host(repo_url)
        if not repo_host:
            return []

        credential_binding = None
        if isinstance(project, dict):
            credential_binding = _normalize_project_credential_binding(project.get("credential_binding"))

        contexts: list[tuple[str, str, dict[str, Any]]] = []
        personal_access_tokens = self._personal_access_tokens_for_repo(repo_url, credential_binding=credential_binding)
        for token in personal_access_tokens:
            pat_host = str(token.get("host") or "")
            if pat_host and repo_host == pat_host:
                payload = dict(token)
                payload["credential_id"] = str(payload.get("token_id") or "").strip()
                contexts.append((GIT_CONNECTION_MODE_PERSONAL_ACCESS_TOKEN, pat_host, payload))

        installation = self._github_connected_installation()
        provider_host = self._github_provider_host()
        if installation is not None and repo_host == provider_host:
            installation_id = int(installation.get("installation_id") or 0)
            if installation_id > 0:
                app_credential_id = f"github_app:{installation_id}"
                normalized_binding = _normalize_project_credential_binding(credential_binding)
                is_allowed = True
                if normalized_binding["mode"] in {
                    PROJECT_CREDENTIAL_BINDING_MODE_SET,
                    PROJECT_CREDENTIAL_BINDING_MODE_SINGLE,
                }:
                    preferred_ids = normalized_binding["credential_ids"]
                    if preferred_ids and app_credential_id not in preferred_ids:
                        is_allowed = False

                if is_allowed:
                    contexts.append(
                        (
                            GITHUB_CONNECTION_MODE_GITHUB_APP,
                            provider_host,
                            {
                                "installation_id": installation_id,
                                "credential_id": app_credential_id,
                                "provider": GIT_PROVIDER_GITHUB,
                                "account_login": str(installation.get("installation_account_login") or ""),
                            },
                        )
                    )
        return contexts

    def _auto_discover_project_credential_binding(
        self,
        repo_url: str,
        credential_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_binding = _normalize_project_credential_binding(credential_binding)
        if (
            normalized_binding["mode"] != PROJECT_CREDENTIAL_BINDING_MODE_AUTO
            or normalized_binding["credential_ids"]
        ):
            return normalized_binding

        normalized_repo_url = str(repo_url or "").strip()
        if not normalized_repo_url:
            return normalized_binding

        discovered_ids = self._resolve_agent_tools_credential_ids(
            {"repo_url": normalized_repo_url, "credential_binding": normalized_binding},
            PROJECT_CREDENTIAL_BINDING_MODE_AUTO,
            [],
        )
        if not discovered_ids:
            return normalized_binding

        # Verify each discovered credential can actually access this specific repo,
        # not just the host. Tokens may be scoped to certain repositories.
        discovered_id_set = set(discovered_ids)
        stub_project: dict[str, Any] = {"repo_url": normalized_repo_url, "credential_binding": normalized_binding}
        all_contexts = self._github_repo_all_auth_contexts(normalized_repo_url, project=stub_project)
        candidate_contexts = [
            ctx for ctx in all_contexts
            if str(ctx[2].get("credential_id") or "").strip() in discovered_id_set
        ]
        if candidate_contexts:
            verified_contexts = self._verify_repo_access_for_contexts(
                normalized_repo_url,
                candidate_contexts,
                context_key="auto-discover",
            )
            if verified_contexts:
                verified_id_set = set(
                    str(ctx[2].get("credential_id") or "").strip()
                    for ctx in verified_contexts
                )
                # Preserve original ordering, keep only verified
                discovered_ids = [cid for cid in discovered_ids if cid in verified_id_set]

        if not discovered_ids:
            return normalized_binding

        return _normalize_project_credential_binding(
            {
                "mode": PROJECT_CREDENTIAL_BINDING_MODE_SET,
                "credential_ids": discovered_ids,
                "source": normalized_binding["source"] or "auto_create",
                "updated_at": _iso_now(),
            }
        )

    def _github_repo_auth_context(
        self,
        repo_url: str,
        project: dict[str, Any] | None = None,
    ) -> tuple[str, str, dict[str, Any]] | None:
        contexts = self._github_repo_all_auth_contexts(repo_url, project=project)
        return contexts[0] if contexts else None

    def _refresh_all_github_git_credentials(
        self,
        contexts: list[tuple[str, str, dict[str, Any]]],
        *,
        context_key: str = "",
    ) -> str:
        lines: list[str] = []
        seen_lines: set[str] = set()
        for mode, host, auth_payload in contexts:
            scheme = GIT_CREDENTIAL_DEFAULT_SCHEME
            if mode == GITHUB_CONNECTION_MODE_GITHUB_APP:
                installation_id = int(auth_payload.get("installation_id") or 0)
                if installation_id <= 0:
                    continue
                token, _expires_at = self._github_installation_token(installation_id)
                username = "x-access-token"
            elif mode == GIT_CONNECTION_MODE_PERSONAL_ACCESS_TOKEN:
                token = str(auth_payload.get("personal_access_token") or "").strip()
                username = str(auth_payload.get("account_login") or "").strip()
                try:
                    scheme = _normalize_github_credential_scheme(
                        auth_payload.get("scheme"),
                        field_name="scheme",
                    )
                except HTTPException:
                    scheme = GIT_CREDENTIAL_DEFAULT_SCHEME
            else:
                continue

            if not token or not username:
                continue

            encoded_username = urllib.parse.quote(username, safe="")
            encoded_secret = urllib.parse.quote(token, safe="")
            line = f"{scheme}://{encoded_username}:{encoded_secret}@{host}\n"
            if line not in seen_lines:
                lines.append(line)
                seen_lines.add(line)

        if not lines:
            return ""

        output_file = self._materialized_credential_file_path(context_key, "merged")
        _write_private_env_file(output_file, "".join(lines))
        return str(output_file)

    @staticmethod
    def _git_scheme_for_auth_context(
        mode: str,
        auth_payload: dict[str, Any],
    ) -> str:
        if mode != GIT_CONNECTION_MODE_PERSONAL_ACCESS_TOKEN:
            return GIT_CREDENTIAL_DEFAULT_SCHEME
        try:
            return _normalize_github_credential_scheme(
                auth_payload.get("scheme"),
                field_name="scheme",
            )
        except HTTPException:
            return GIT_CREDENTIAL_DEFAULT_SCHEME

    def _verify_repo_access_for_contexts(
        self,
        repo_url: str,
        contexts: list[tuple[str, str, dict[str, Any]]],
        *,
        context_key: str = "",
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Probe each credential context with ``git ls-remote`` and return only those that can access *repo_url*."""
        normalized_repo_url = str(repo_url or "").strip()
        if not normalized_repo_url or not contexts:
            return []

        normalized_context_key = str(context_key or "").strip()
        if normalized_context_key:
            probe_prefix = f"{normalized_context_key}:probe"
        else:
            repo_digest = hashlib.sha256(normalized_repo_url.encode("utf-8")).hexdigest()[:12]
            probe_prefix = f"repo-auth-probe:{repo_digest}"

        verified: list[tuple[str, str, dict[str, Any]]] = []
        for index, context in enumerate(contexts):
            mode, host, auth_payload = context
            credential_id = str(auth_payload.get("credential_id") or "").strip() or f"{mode}:{host}:{index}"
            probe_context_key = f"{probe_prefix}:{credential_id}:{index}"

            try:
                credentials_file = self._refresh_all_github_git_credentials(
                    [context],
                    context_key=probe_context_key,
                )
            except HTTPException:
                continue
            if not credentials_file:
                continue

            probe_env = self._git_env_for_credentials_file(
                credentials_file,
                host,
                scheme=self._git_scheme_for_auth_context(mode, auth_payload),
            )
            probe_result = _run(
                ["git", "ls-remote", "--exit-code", normalized_repo_url, "HEAD"],
                capture=True,
                check=False,
                env=probe_env,
            )
            if probe_result.returncode == 0:
                verified.append(context)

        return verified

    def _ordered_repo_auth_contexts_for_git(
        self,
        repo_url: str,
        contexts: list[tuple[str, str, dict[str, Any]]],
        *,
        context_key: str = "",
    ) -> list[tuple[str, str, dict[str, Any]]]:
        if len(contexts) <= 1:
            return contexts

        verified = self._verify_repo_access_for_contexts(
            repo_url, contexts, context_key=context_key,
        )
        if not verified:
            return contexts

        verified_set = set(id(ctx) for ctx in verified)
        unverified = [ctx for ctx in contexts if id(ctx) not in verified_set]
        return [*verified, *unverified]

    def _github_git_env_for_repo(
        self,
        repo_url: str,
        project: dict[str, Any] | None = None,
        *,
        context_key: str = "",
    ) -> dict[str, str]:
        ordered_contexts = self._ordered_repo_auth_contexts_for_git(
            repo_url,
            self._github_repo_all_auth_contexts(repo_url, project=project),
            context_key=context_key,
        )
        if not ordered_contexts:
            return {}
        credentials_file = self._refresh_all_github_git_credentials(
            ordered_contexts,
            context_key=context_key,
        )
        if not credentials_file:
            return {}
        mode, host, auth_payload = ordered_contexts[0]
        return self._git_env_for_credentials_file(
            credentials_file,
            host,
            scheme=self._git_scheme_for_auth_context(mode, auth_payload),
        )

    def _github_git_args_for_repo(
        self,
        repo_url: str,
        project: dict[str, Any] | None = None,
        *,
        context_key: str = "",
    ) -> list[str]:
        ordered_contexts = self._ordered_repo_auth_contexts_for_git(
            repo_url,
            self._github_repo_all_auth_contexts(repo_url, project=project),
            context_key=context_key,
        )
        if not ordered_contexts:
            return []
        credentials_file = self._refresh_all_github_git_credentials(
            ordered_contexts,
            context_key=context_key,
        )
        if not credentials_file:
            return []
        _mode, host, _auth_payload = ordered_contexts[0]
        return [
            "--git-credential-file",
            credentials_file,
            "--git-credential-host",
            host,
        ]

    def _github_git_identity_env_vars_for_repo(
        self,
        repo_url: str,
        project: dict[str, Any] | None = None,
    ) -> list[str]:
        context = self._github_repo_auth_context(repo_url, project=project)
        if context is None:
            return []
        mode, _host, auth_payload = context
        if mode != GIT_CONNECTION_MODE_PERSONAL_ACCESS_TOKEN:
            return []

        git_user_name = str(auth_payload.get("git_user_name") or auth_payload.get("account_name") or "").strip()
        if not git_user_name:
            git_user_name = str(auth_payload.get("account_login") or "").strip()
        git_user_email = str(auth_payload.get("git_user_email") or auth_payload.get("account_email") or "").strip()
        if not git_user_name or not git_user_email:
            return []
        return [
            f"AGENT_HUB_GIT_USER_NAME={git_user_name}",
            f"AGENT_HUB_GIT_USER_EMAIL={git_user_email}",
        ]

    def _openai_account_payload(self) -> dict[str, Any]:
        account_connected, auth_mode = _read_codex_auth(self.openai_codex_auth_file)
        updated_at = ""
        if self.openai_codex_auth_file.exists():
            try:
                updated_at = _iso_from_timestamp(self.openai_codex_auth_file.stat().st_mtime)
            except OSError:
                updated_at = ""
        return {
            "account_connected": account_connected,
            "account_auth_mode": auth_mode,
            "account_updated_at": updated_at,
        }

    def openai_auth_status(self) -> dict[str, Any]:
        api_key = _read_openai_api_key(self.openai_credentials_file)
        updated_at = ""
        if self.openai_credentials_file.exists():
            try:
                updated_at = _iso_from_timestamp(self.openai_credentials_file.stat().st_mtime)
            except OSError:
                updated_at = ""
        account_payload = self._openai_account_payload()
        return {
            "provider": "openai",
            "connected": bool(api_key),
            "key_hint": _mask_secret(api_key) if api_key else "",
            "updated_at": updated_at,
            "account_connected": account_payload["account_connected"],
            "account_auth_mode": account_payload["account_auth_mode"],
            "account_updated_at": account_payload["account_updated_at"],
        }

    def github_app_auth_status(self) -> dict[str, Any]:
        installation = self._github_connected_installation()
        app_configured = self.github_app_settings is not None and not self.github_app_settings_error
        installation_id = int(installation.get("installation_id") or 0) if installation else 0

        updated_at = ""
        if self.github_app_installation_file.exists():
            try:
                updated_at = _iso_from_timestamp(self.github_app_installation_file.stat().st_mtime)
            except OSError:
                updated_at = ""
        elif self.github_app_settings_file.exists():
            try:
                updated_at = _iso_from_timestamp(self.github_app_settings_file.stat().st_mtime)
            except OSError:
                updated_at = ""

        return {
            "provider": "github_app",
            "connected": bool(app_configured and installation_id > 0),
            "app_configured": app_configured,
            "app_slug": self.github_app_settings.app_slug if self.github_app_settings else "",
            "install_url": self._github_install_url(),
            "installation_id": installation_id,
            "installation_account_login": str(installation.get("account_login") or "") if installation else "",
            "installation_account_type": str(installation.get("account_type") or "") if installation else "",
            "repository_selection": str(installation.get("repository_selection") or "") if installation else "",
            "connection_host": self._github_provider_host(),
            "updated_at": updated_at,
            "error": str(self.github_app_settings_error or ""),
        }

    def _personal_access_tokens_status(self, provider: str) -> dict[str, Any]:
        normalized_provider = (
            GIT_PROVIDER_GITLAB if str(provider or "").strip().lower() == GIT_PROVIDER_GITLAB else GIT_PROVIDER_GITHUB
        )
        token_records = self._connected_personal_access_tokens(normalized_provider)
        entries: list[dict[str, Any]] = []
        for token_record in token_records:
            token_value = str(token_record.get("personal_access_token") or "").strip()
            entries.append(
                {
                    "token_id": str(token_record.get("token_id") or "").strip(),
                    "token_hint": _mask_secret(token_value) if token_value else "",
                    "host": str(token_record.get("host") or "").strip(),
                    "scheme": _normalize_github_credential_scheme(token_record.get("scheme"), field_name="scheme"),
                    "provider": normalized_provider,
                    "account_login": str(token_record.get("account_login") or "").strip(),
                    "account_name": str(token_record.get("account_name") or "").strip(),
                    "account_email": str(token_record.get("account_email") or "").strip(),
                    "account_id": str(token_record.get("account_id") or "").strip(),
                    "git_user_name": str(token_record.get("git_user_name") or "").strip(),
                    "git_user_email": str(token_record.get("git_user_email") or "").strip(),
                    "token_scopes": str(token_record.get("token_scopes") or "").strip(),
                    "verified_at": str(token_record.get("verified_at") or "").strip(),
                    "connected_at": str(token_record.get("connected_at") or "").strip(),
                }
            )

        token_file = self._token_store_file_for_provider(normalized_provider)
        updated_at = ""
        if token_file.exists():
            try:
                updated_at = _iso_from_timestamp(token_file.stat().st_mtime)
            except OSError:
                updated_at = ""

        provider_key = "gitlab_tokens" if normalized_provider == GIT_PROVIDER_GITLAB else "github_tokens"
        default_host = (
            "gitlab.com" if normalized_provider == GIT_PROVIDER_GITLAB else self._github_provider_host()
        )
        return {
            "provider": provider_key,
            "git_provider": normalized_provider,
            "connected": bool(entries),
            "token_count": len(entries),
            "tokens": entries,
            "default_host": default_host,
            "updated_at": updated_at,
        }

    def github_tokens_status(self) -> dict[str, Any]:
        return self._personal_access_tokens_status(GIT_PROVIDER_GITHUB)

    def gitlab_tokens_status(self) -> dict[str, Any]:
        return self._personal_access_tokens_status(GIT_PROVIDER_GITLAB)

    def _chat_title_generation_auth(self) -> tuple[str, str]:
        account_connected, _ = _read_codex_auth(self.openai_codex_auth_file)
        if account_connected:
            return CHAT_TITLE_AUTH_MODE_ACCOUNT, ""
        api_key = _read_openai_api_key(self.openai_credentials_file) or ""
        if api_key:
            return CHAT_TITLE_AUTH_MODE_API_KEY, api_key
        return CHAT_TITLE_AUTH_MODE_NONE, ""

    def _generate_chat_title_with_resolved_auth(
        self,
        auth_mode: str,
        api_key: str,
        user_prompts: list[str],
    ) -> tuple[str, str]:
        if auth_mode == CHAT_TITLE_AUTH_MODE_ACCOUNT:
            title = _codex_generate_chat_title(
                host_agent_home=self.host_agent_home,
                host_codex_dir=self.host_codex_dir,
                user_prompts=user_prompts,
                max_chars=CHAT_TITLE_MAX_CHARS,
            )
            return title, CHAT_TITLE_ACCOUNT_MODEL
        if auth_mode == CHAT_TITLE_AUTH_MODE_API_KEY:
            title = _openai_generate_chat_title(
                api_key=api_key,
                user_prompts=user_prompts,
                max_chars=CHAT_TITLE_MAX_CHARS,
            )
            return title, CHAT_TITLE_OPENAI_MODEL
        raise RuntimeError(CHAT_TITLE_NO_CREDENTIALS_ERROR)

    def _credential_catalog(self) -> list[dict[str, Any]]:
        credentials: list[dict[str, Any]] = []

        github_app_status = self.github_app_auth_status()
        if github_app_status.get("connected"):
            installation_id = int(github_app_status.get("installation_id") or 0)
            if installation_id > 0:
                installation_login = str(github_app_status.get("installation_account_login") or "")
                credentials.append(
                    {
                        "credential_id": f"github_app:{installation_id}",
                        "kind": "github_app_installation",
                        "provider": GIT_PROVIDER_GITHUB,
                        "host": self._github_provider_host(),
                        "scheme": GIT_CREDENTIAL_DEFAULT_SCHEME,
                        "account_login": installation_login,
                        "account_name": installation_login,
                        "connected_at": str(github_app_status.get("updated_at") or ""),
                        "summary": f"GitHub App installation #{installation_id}"
                        + (f" ({installation_login})" if installation_login else ""),
                    }
                )

        for provider in (GIT_PROVIDER_GITHUB, GIT_PROVIDER_GITLAB):
            for token in self._connected_personal_access_tokens(provider):
                token_id = str(token.get("token_id") or "").strip()
                if not token_id:
                    continue
                account_login = str(token.get("account_login") or "").strip()
                host = str(token.get("host") or "").strip()
                credentials.append(
                    {
                        "credential_id": token_id,
                        "kind": "personal_access_token",
                        "provider": provider,
                        "host": host,
                        "scheme": _normalize_github_credential_scheme(token.get("scheme"), field_name="scheme"),
                        "account_login": account_login,
                        "account_name": str(token.get("account_name") or "").strip(),
                        "connected_at": str(token.get("connected_at") or "").strip(),
                        "summary": (
                            f"{provider.capitalize()} token"
                            f"{f' ({account_login})' if account_login else ''}"
                            f"{f' on {host}' if host else ''}"
                        ),
                    }
                )

        credentials.sort(
            key=lambda entry: (
                str(entry.get("provider") or ""),
                str(entry.get("host") or ""),
                str(entry.get("account_login") or ""),
                str(entry.get("credential_id") or ""),
            )
        )
        return credentials

    def auth_settings_payload(self) -> dict[str, Any]:
        return {
            "providers": {
                "openai": self.openai_auth_status(),
                "github_app": self.github_app_auth_status(),
                "github_tokens": self.github_tokens_status(),
                "gitlab_tokens": self.gitlab_tokens_status(),
            },
            "credential_catalog": self._credential_catalog(),
        }

    def test_openai_chat_title_generation(self, prompt: Any) -> dict[str, Any]:
        submitted = _compact_whitespace(str(prompt or "")).strip()
        if not submitted:
            raise HTTPException(status_code=400, detail="prompt is required.")

        auth_status = self.openai_auth_status()
        auth_mode, api_key = self._chat_title_generation_auth()
        connectivity = {
            "api_key_connected": bool(auth_status.get("connected")),
            "api_key_hint": str(auth_status.get("key_hint") or ""),
            "api_key_updated_at": str(auth_status.get("updated_at") or ""),
            "account_connected": bool(auth_status.get("account_connected")),
            "account_auth_mode": str(auth_status.get("account_auth_mode") or ""),
            "account_updated_at": str(auth_status.get("account_updated_at") or ""),
            "title_generation_auth_mode": auth_mode,
        }

        issues: list[str] = []
        model = (
            CHAT_TITLE_OPENAI_MODEL
            if auth_mode == CHAT_TITLE_AUTH_MODE_API_KEY
            else CHAT_TITLE_ACCOUNT_MODEL
            if auth_mode == CHAT_TITLE_AUTH_MODE_ACCOUNT
            else ""
        )
        if auth_mode == CHAT_TITLE_AUTH_MODE_NONE:
            error = CHAT_TITLE_NO_CREDENTIALS_ERROR
            issues.append(error)
            return {
                "ok": False,
                "title": "",
                "model": model,
                "prompt": submitted,
                "error": error,
                "issues": issues,
                "connectivity": connectivity,
            }

        try:
            resolved_title, model = self._generate_chat_title_with_resolved_auth(
                auth_mode=auth_mode,
                api_key=api_key,
                user_prompts=[submitted],
            )
        except Exception as exc:
            error = str(exc)
            if error:
                issues.append(error)
            return {
                "ok": False,
                "title": "",
                "model": model,
                "prompt": submitted,
                "error": error,
                "issues": issues,
                "connectivity": connectivity,
            }

        return {
            "ok": True,
            "title": resolved_title,
            "model": model,
            "prompt": submitted,
            "error": "",
            "issues": issues,
            "connectivity": connectivity,
        }

    @staticmethod
    def _dedupe_entries(entries: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for entry in entries:
            normalized = str(entry or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    def _auto_config_prompt(self, repo_url: str, branch: str) -> str:
        return _render_prompt_template(
            PROMPT_AUTO_CONFIGURE_PROJECT_FILE,
            repo_url=repo_url,
            branch=branch,
        )

    def _normalize_auto_config_setup_script(self, raw_script: Any) -> str:
        script = str(raw_script or "").replace("\r\n", "\n").replace("\r", "\n")
        commands = [line.strip() for line in script.split("\n") if line.strip()]
        if not commands:
            return ""
        lowered = [line.lower() for line in commands]
        has_apt_install = any(("apt-get install" in line) or ("apt install" in line) for line in lowered)
        has_apt_update = any(("apt-get update" in line) or ("apt update" in line) for line in lowered)
        if has_apt_install and not has_apt_update:
            commands.insert(0, "apt-get update")
        return "\n".join(commands)

    @staticmethod
    def _normalize_auto_config_shell_path(path_value: str) -> str:
        normalized = str(path_value or "").strip().strip("\"'").replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.rstrip("/") or "."

    @staticmethod
    def _extract_auto_config_option_path(command: str, pattern: re.Pattern[str]) -> str:
        match = pattern.search(str(command or ""))
        if not match:
            return ""
        return HubState._normalize_auto_config_shell_path(str(match.group(1) or ""))

    @staticmethod
    def _auto_config_setup_scope_matches(left_scope: str, right_scope: str) -> bool:
        left = HubState._normalize_auto_config_shell_path(left_scope)
        right = HubState._normalize_auto_config_shell_path(right_scope)
        if left == right:
            return True
        if left == "." or right == ".":
            return left == right
        return left.endswith(f"/{right}") or right.endswith(f"/{left}")

    def _auto_config_setup_signature_for_command(self, command: str, cwd: str) -> tuple[str, str] | None:
        normalized = _compact_whitespace(str(command or "")).strip()
        if not normalized:
            return None
        normalized_cwd = self._normalize_auto_config_shell_path(cwd)

        if AUTO_CONFIG_SETUP_UV_SYNC_RE.search(normalized):
            return "uv_sync", normalized_cwd

        if AUTO_CONFIG_SETUP_YARN_INSTALL_RE.search(normalized):
            cwd_path = self._extract_auto_config_option_path(normalized, AUTO_CONFIG_SETUP_CWD_RE)
            return "yarn_install", self._normalize_auto_config_shell_path(cwd_path or normalized_cwd)

        if AUTO_CONFIG_SETUP_NPM_CI_RE.search(normalized):
            prefix_path = self._extract_auto_config_option_path(normalized, AUTO_CONFIG_SETUP_PREFIX_RE)
            return "npm_ci", self._normalize_auto_config_shell_path(prefix_path or normalized_cwd)

        return None

    def _auto_config_setup_signatures_from_shell(self, shell_command: str) -> set[tuple[str, str]]:
        signatures: set[tuple[str, str]] = set()
        cwd = "."
        for segment in AUTO_CONFIG_SETUP_CHAIN_SPLIT_RE.split(str(shell_command or "").strip()):
            normalized = _compact_whitespace(segment).strip()
            if not normalized:
                continue
            cd_match = AUTO_CONFIG_SETUP_CD_RE.match(normalized)
            if cd_match:
                cwd = self._normalize_auto_config_shell_path(str(cd_match.group(1) or ""))
                continue
            signature = self._auto_config_setup_signature_for_command(normalized, cwd)
            if signature is not None:
                signatures.add(signature)
        return signatures

    @staticmethod
    def _dockerfile_run_commands(dockerfile: Path) -> list[str]:
        try:
            raw_text = dockerfile.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return []

        instructions: list[str] = []
        current = ""
        for raw_line in raw_text.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if current:
                current = f"{current} {stripped}"
            else:
                current = stripped
            if current.endswith("\\"):
                current = current[:-1].rstrip()
                continue
            instructions.append(current)
            current = ""
        if current:
            instructions.append(current)

        run_commands: list[str] = []
        for instruction in instructions:
            lowered = instruction.lower()
            if not lowered.startswith("run "):
                continue
            run_commands.append(instruction[4:].strip())
        return run_commands

    def _auto_config_setup_signatures_from_repo_dockerfile(self, dockerfile: Path) -> set[tuple[str, str]]:
        signatures: set[tuple[str, str]] = set()
        for run_command in self._dockerfile_run_commands(dockerfile):
            signatures.update(self._auto_config_setup_signatures_from_shell(run_command))
        return signatures

    def _auto_config_signature_in(self, signature: tuple[str, str], known: set[tuple[str, str]]) -> bool:
        kind, scope = signature
        for known_kind, known_scope in known:
            if kind != known_kind:
                continue
            if self._auto_config_setup_scope_matches(scope, known_scope):
                return True
        return False

    def _resolve_auto_config_repo_dockerfile(self, workspace: Path, base_image_value: str) -> Path | None:
        raw_value = str(base_image_value or "").strip()
        if not raw_value:
            return None
        candidate = (workspace / raw_value).resolve()
        workspace_root = workspace.resolve()
        try:
            candidate.relative_to(workspace_root)
        except ValueError:
            return None
        dockerfile = candidate / "Dockerfile" if candidate.is_dir() else candidate
        if not dockerfile.is_file():
            return None
        return dockerfile

    def _dedupe_setup_script_commands_present_in_repo_dockerfile(
        self,
        workspace: Path,
        base_image_mode: str,
        base_image_value: str,
        setup_script: str,
    ) -> str:
        normalized_script = str(setup_script or "").strip()
        if not normalized_script:
            return ""
        if base_image_mode != "repo_path":
            return normalized_script

        dockerfile = self._resolve_auto_config_repo_dockerfile(workspace, base_image_value)
        if dockerfile is None:
            return normalized_script
        docker_signatures = self._auto_config_setup_signatures_from_repo_dockerfile(dockerfile)
        if not docker_signatures:
            return normalized_script

        kept_lines: list[str] = []
        for raw_line in normalized_script.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            line_signatures = self._auto_config_setup_signatures_from_shell(line)
            if line_signatures and all(self._auto_config_signature_in(sig, docker_signatures) for sig in line_signatures):
                continue
            kept_lines.append(line)
        return "\n".join(kept_lines)

    @staticmethod
    def _is_auto_config_cache_signal_file(path: Path, workspace: Path) -> bool:
        try:
            relative = path.relative_to(workspace)
        except ValueError:
            return False
        parts = [part.lower() for part in relative.parts]
        if not parts:
            return False
        if any(part in AUTO_CONFIG_CACHE_SIGNAL_IGNORED_PATH_PARTS for part in parts[:-1]):
            return False
        if any(part in AUTO_CONFIG_CACHE_SIGNAL_DOC_DIRS for part in parts[:-1]):
            return False
        filename = parts[-1]
        if filename in AUTO_CONFIG_CACHE_SIGNAL_FILENAMES:
            return True
        if "dockerfile" in filename:
            return True
        return path.suffix.lower() in AUTO_CONFIG_CACHE_SIGNAL_SUFFIXES

    def _detected_auto_config_cache_backends(self, workspace: Path) -> set[str]:
        detected: set[str] = set()
        files_scanned = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [name for name in dirs if name not in AUTO_CONFIG_CACHE_SIGNAL_IGNORED_DIRS]
            for filename in files:
                path = Path(root) / filename
                if not self._is_auto_config_cache_signal_file(path, workspace):
                    continue
                files_scanned += 1
                if files_scanned > AUTO_CONFIG_CACHE_SIGNAL_MAX_FILES:
                    return detected
                try:
                    if path.stat().st_size > 1_500_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                lowered = text.lower()
                if "ccache" in lowered and any(pattern.search(text) for pattern in AUTO_CONFIG_CCACHE_SIGNAL_PATTERNS):
                    detected.add("ccache")
                if "sccache" in lowered and any(pattern.search(text) for pattern in AUTO_CONFIG_SCCACHE_SIGNAL_PATTERNS):
                    detected.add("sccache")
                if len(detected) == 2:
                    return detected
        return detected

    @staticmethod
    def _cache_mount_backend_from_container_path(container_path: str) -> str:
        normalized = str(container_path or "").strip().replace("\\", "/").rstrip("/").lower()
        if not normalized:
            return ""
        if re.search(r"(?:^|/)\.?ccache(?:$|/)", normalized):
            return "ccache"
        if re.search(r"(?:^|/)\.cache/sccache(?:$|/)", normalized):
            return "sccache"
        if re.search(r"(?:^|/)\.?sccache(?:$|/)", normalized):
            return "sccache"
        if re.search(r"(?:^|/)\.scache(?:$|/)", normalized):
            return "sccache"
        return ""

    @staticmethod
    def _cache_mount_backend_from_entry(entry: str) -> str:
        if ":" not in entry:
            return ""
        _host, container_raw = entry.split(":", 1)
        return HubState._cache_mount_backend_from_container_path(container_raw)

    def _augment_auto_config_cache_mounts(self, workspace: Path, rw_mounts: list[str]) -> list[str]:
        mounted = self._dedupe_entries(list(rw_mounts))
        detected = self._detected_auto_config_cache_backends(workspace)
        filtered: list[str] = []
        existing: set[str] = set()
        for entry in mounted:
            backend = self._cache_mount_backend_from_entry(entry)
            if backend:
                continue
            if entry in existing:
                continue
            filtered.append(entry)
            existing.add(entry)

        container_home = DEFAULT_CONTAINER_HOME
        cache_specs = [
            ("ccache", Path.home().resolve() / ".ccache", f"{container_home}/.ccache"),
            ("sccache", Path.home().resolve() / ".cache" / "sccache", f"{container_home}/.cache/sccache"),
        ]
        for token, host_path, container_path in cache_specs:
            if token not in detected:
                continue
            try:
                host_path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise MountVisibilityError(
                    f"Auto-config cache mount host path is not writable: {host_path}"
                ) from exc
            entry = f"{host_path}:{container_path}"
            if entry in existing:
                continue
            filtered.append(entry)
            existing.add(entry)
        return filtered

    def _normalize_auto_config_repo_path(self, workspace: Path, raw_value: Any) -> str:
        value = str(raw_value or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="Auto-config recommendation requires base_image_value for repo_path mode.")
        candidate = Path(value).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
        workspace_root = workspace.resolve()
        try:
            relative = resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Auto-config base_image_value must stay inside the repository: {value}",
            ) from exc
        if not (resolved.is_file() or resolved.is_dir()):
            raise HTTPException(
                status_code=400,
                detail=f"Auto-config base_image_value does not exist in repository: {value}",
            )
        return relative.as_posix()

    @staticmethod
    def _normalize_auto_config_mount_path(path_value: str) -> str:
        normalized = str(path_value or "").strip().strip("\"'").replace("\\", "/")
        if normalized.startswith("/"):
            normalized = normalized.split(":", 1)[0]
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
        if len(normalized) > 1:
            normalized = normalized.rstrip("/")
        return normalized.lower()

    @classmethod
    def _is_auto_config_docker_socket_path(cls, path_value: str) -> bool:
        normalized = cls._normalize_auto_config_mount_path(path_value)
        if not normalized:
            return False
        if normalized in AUTO_CONFIG_DOCKER_SOCKET_PATHS:
            return True
        return normalized.endswith("/docker.sock")

    @staticmethod
    def _is_auto_config_container_workspace_mount(
        container_path: str,
        reserved_container_workspace: str | None = None,
    ) -> bool:
        normalized_container = HubState._normalize_auto_config_mount_path(container_path)
        if not normalized_container:
            return False
        normalized_workspace = HubState._normalize_auto_config_mount_path(reserved_container_workspace or "")
        if not normalized_workspace or normalized_workspace == "/":
            return False
        if normalized_container == normalized_workspace:
            return True
        return normalized_container.startswith(f"{normalized_workspace}/")

    def _normalize_auto_config_mounts(
        self,
        entries: list[str],
        direction: str,
        *,
        reserved_container_workspace: str | None = None,
    ) -> list[str]:
        normalized_entries: list[str] = []
        for raw_entry in entries:
            if ":" not in raw_entry:
                raise HTTPException(status_code=400, detail=f"Invalid auto-config {direction} mount '{raw_entry}'.")
            host_raw, container_raw = raw_entry.split(":", 1)
            if self._is_auto_config_docker_socket_path(host_raw) or self._is_auto_config_docker_socket_path(
                container_raw
            ):
                raise MountVisibilityError(
                    f"Auto-config {direction} mount '{raw_entry}' is invalid: docker socket mounts are not allowed."
                )
            container = container_raw.strip()
            if not container.startswith("/"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid auto-config container path for {direction} mount '{raw_entry}'.",
                )
            host_path = Path(host_raw).expanduser()
            if not host_path.exists():
                raise MountVisibilityError(
                    f"Auto-config {direction} mount host path does not exist: {host_raw}"
                )
            if self._is_auto_config_container_workspace_mount(
                container,
                reserved_container_workspace=reserved_container_workspace,
            ):
                raise MountVisibilityError(
                    f"Auto-config {direction} mount '{raw_entry}' targets reserved workspace path."
                )
            normalized_entries.append(f"{host_path}:{container}")
        return _parse_mounts(normalized_entries, direction)

    def _normalize_auto_config_recommendation(
        self,
        raw_payload: dict[str, Any],
        workspace: Path,
        project_container_workspace: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=400, detail="Auto-config output must be a JSON object.")

        base_image_mode = _normalize_base_image_mode(raw_payload.get("base_image_mode"))
        base_image_value = str(raw_payload.get("base_image_value") or "").strip()
        if base_image_mode == "repo_path":
            base_image_value = self._normalize_auto_config_repo_path(workspace, base_image_value)

        setup_script = self._normalize_auto_config_setup_script(raw_payload.get("setup_script"))
        setup_script = self._dedupe_setup_script_commands_present_in_repo_dockerfile(
            workspace=workspace,
            base_image_mode=base_image_mode,
            base_image_value=base_image_value,
            setup_script=setup_script,
        )
        default_ro_mounts = self._normalize_auto_config_mounts(
            _empty_list(raw_payload.get("default_ro_mounts")),
            "default read-only mount",
            reserved_container_workspace=project_container_workspace,
        )
        default_rw_mounts = self._normalize_auto_config_mounts(
            _empty_list(raw_payload.get("default_rw_mounts")),
            "default read-write mount",
            reserved_container_workspace=project_container_workspace,
        )
        default_rw_mounts = self._augment_auto_config_cache_mounts(workspace, default_rw_mounts)
        default_env_vars = _parse_env_vars(_empty_list(raw_payload.get("default_env_vars")))

        notes_raw = _compact_whitespace(str(raw_payload.get("notes") or "")).strip()
        if len(notes_raw) > AUTO_CONFIG_NOTES_MAX_CHARS:
            notes = notes_raw[: AUTO_CONFIG_NOTES_MAX_CHARS - 1].rstrip() + "…"
        else:
            notes = notes_raw

        return {
            "base_image_mode": base_image_mode,
            "base_image_value": base_image_value,
            "setup_script": setup_script,
            "default_ro_mounts": self._dedupe_entries(default_ro_mounts),
            "default_rw_mounts": self._dedupe_entries(default_rw_mounts),
            "default_env_vars": self._dedupe_entries(default_env_vars),
            "notes": notes,
        }

    @staticmethod
    def _dockerfile_path_score(relative_path: str) -> tuple[int, int, str]:
        normalized = str(relative_path or "").strip().replace("\\", "/")
        lowered = normalized.lower()
        parts = [part for part in lowered.split("/") if part]
        score = 0
        filename = parts[-1] if parts else lowered
        if filename == "dockerfile":
            score += 40
        elif "dockerfile" in filename:
            score += 20
        if "ci" in parts:
            score += 80
        if "docker" in lowered:
            score += 40
        if "devcontainer" in parts:
            score += 60
        if any(part in {"x86", "amd64"} for part in parts):
            score += 15
        if any(part in {"test", "tests", "example", "examples"} for part in parts):
            score -= 20
        return score, -len(parts), normalized

    def _infer_repo_dockerfile_path(self, workspace: Path) -> str:
        candidates: list[tuple[int, int, str]] = []
        ignored_dirs = {
            ".git",
            ".hg",
            ".svn",
            ".venv",
            "venv",
            "node_modules",
            "build",
            "dist",
            "out",
            "target",
        }
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
            for filename in files:
                lowered = filename.lower()
                if lowered != "dockerfile" and "dockerfile" not in lowered:
                    continue
                absolute_path = Path(root) / filename
                try:
                    relative_path = absolute_path.resolve().relative_to(workspace.resolve()).as_posix()
                except ValueError:
                    continue
                candidates.append(self._dockerfile_path_score(relative_path))
        if not candidates:
            return ""
        candidates.sort(reverse=True)
        return candidates[0][2]

    @staticmethod
    def _iter_text_files_for_make_targets(workspace: Path) -> list[Path]:
        preferred_roots = [
            workspace / ".github" / "workflows",
            workspace / "ci",
            workspace / "docker",
            workspace / "scripts",
        ]
        output: list[Path] = []
        seen: set[Path] = set()
        for filename in ("AGENTS.md", "README.md", "README", "Makefile", "makefile"):
            candidate = workspace / filename
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                output.append(candidate)
        for root in preferred_roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path in seen:
                    continue
                seen.add(path)
                output.append(path)
        return output

    @staticmethod
    def _make_target_context_weight(target: str, context: str) -> int:
        score = 3
        lowered_target = str(target or "").strip().lower()
        lowered_context = str(context or "").strip().lower()
        if not lowered_target:
            return 0

        if any(token in lowered_context for token in ("at a minimum", "minimum", "first", "before you can", "bootstrap")):
            score += 6
        if any(token in lowered_context for token in ("cross build", "cross-build", "host tools", "toolchain")):
            score += 3
        if any(token in lowered_context for token in ("run:", "steps:", "workflow", "pipeline", "ci")):
            score += 2
        if lowered_target in {"check", "test", "tests", "lint", "format", "clean"}:
            score -= 3
        if any(token in lowered_target for token in ("test", "lint", "format", "clean")):
            score -= 2
        return score

    def _infer_make_sh_target(self, workspace: Path) -> str:
        make_script = workspace / "make.sh"
        if not make_script.is_file():
            return ""

        pattern = re.compile(r"(?:^|[\s\"'`])(?:\./)?make\.sh\s+([A-Za-z0-9_.:-]+)")
        counts: dict[str, int] = {}
        for path in self._iter_text_files_for_make_targets(workspace):
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in pattern.finditer(text):
                target = str(match.group(1) or "").strip()
                if not target or target.startswith("-"):
                    continue
                context_start = max(0, match.start() - 120)
                context_end = min(len(text), match.end() + 120)
                context = text[context_start:context_end]
                counts[target] = counts.get(target, 0) + self._make_target_context_weight(target, context)

        if counts:
            ranked = sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0]))
            return ranked[0][0]
        return ""

    def _suggest_make_sh_command(self, workspace: Path) -> str:
        make_script = workspace / "make.sh"
        if not make_script.is_file():
            return ""
        prefix = "./make.sh" if os.access(make_script, os.X_OK) else "bash make.sh"
        target = self._infer_make_sh_target(workspace)
        if target:
            return f"{prefix} {target}"
        return prefix

    def _apply_auto_config_repository_hints(
        self,
        recommendation: dict[str, Any],
        workspace: Path,
    ) -> dict[str, Any]:
        next_recommendation = dict(recommendation)
        dockerfile_path = self._infer_repo_dockerfile_path(workspace)
        current_mode = _normalize_base_image_mode(next_recommendation.get("base_image_mode"))
        current_value = str(next_recommendation.get("base_image_value") or "").strip()

        if dockerfile_path:
            dockerfile_score, _depth_score, _path = self._dockerfile_path_score(dockerfile_path)
            should_use_repo_dockerfile = (
                current_mode != "repo_path" or not current_value
            ) and (dockerfile_score >= AUTO_CONFIG_REPO_DOCKERFILE_MIN_SCORE or not current_value)
            if should_use_repo_dockerfile:
                next_recommendation["base_image_mode"] = "repo_path"
                next_recommendation["base_image_value"] = dockerfile_path

        make_command = self._suggest_make_sh_command(workspace)
        if make_command:
            setup_script = str(next_recommendation.get("setup_script") or "").strip()
            inferred_mode = _normalize_base_image_mode(next_recommendation.get("base_image_mode"))
            if not setup_script:
                next_recommendation["setup_script"] = make_command
            elif inferred_mode == "repo_path" and " " in make_command:
                next_recommendation["setup_script"] = make_command
            elif "make.sh" not in setup_script:
                next_recommendation["setup_script"] = f"{setup_script}\n{make_command}"

        notes = _compact_whitespace(str(next_recommendation.get("notes") or "")).strip()
        if dockerfile_path:
            note_addition = f"selected repository Dockerfile: {dockerfile_path}"
            notes = f"{notes}; {note_addition}" if notes else note_addition
        next_recommendation["notes"] = notes
        return next_recommendation

    def _runtime_identity_for_workspace(self, workspace: Path) -> tuple[int, int, str]:
        del workspace
        return int(self.local_uid), int(self.local_gid), self.local_supp_gids

    def _runtime_run_mode(self) -> str:
        if self.runtime_config is None:
            return DEFAULT_RUNTIME_RUN_MODE
        return str(self.runtime_config.runtime.run_mode or DEFAULT_RUNTIME_RUN_MODE)

    def _prepare_agent_cli_command(
        self,
        *,
        workspace: Path,
        container_project_name: str,
        runtime_config_file: Path,
        agent_type: str,
        run_mode: str,
        agent_tools_url: str,
        agent_tools_token: str,
        agent_tools_project_id: str = "",
        agent_tools_chat_id: str = "",
        ready_ack_guid: str = "",
        repo_url: str = "",
        project: dict[str, Any] | None = None,
        snapshot_tag: str = "",
        ro_mounts: list[str] | None = None,
        rw_mounts: list[str] | None = None,
        env_vars: list[str] | None = None,
        artifacts_url: str = "",
        artifacts_token: str = "",
        resume: bool = False,
        allocate_tty: bool = True,
        context_key: str = "",
        extra_args: list[str] | None = None,
        setup_script: str = "",
        prepare_snapshot_only: bool = False,
        project_in_image: bool = False,
        runtime_tmp_mount: str = "",
    ) -> list[str]:
        runtime_uid, runtime_gid, runtime_supp_gids = self._runtime_identity_for_workspace(workspace)
        normalized_agent_type = _normalize_chat_agent_type(agent_type, strict=True)
        agent_command = _agent_command_for_type(normalized_agent_type)
        project_base_args: list[str] = []
        if snapshot_tag:
            self._append_project_base_args(project_base_args, workspace, project)

        normalized_ro_mounts = [str(mount) for mount in (ro_mounts or []) if str(mount or "").strip()]
        normalized_rw_mounts = [str(mount) for mount in (rw_mounts or []) if str(mount or "").strip()]
        normalized_runtime_tmp_mount = str(runtime_tmp_mount or "").strip()
        if normalized_runtime_tmp_mount:
            has_workspace_tmp_mount = _contains_container_mount_target(
                [*normalized_ro_mounts, *normalized_rw_mounts],
                DEFAULT_CONTAINER_TMP_DIR,
            )
            if not has_workspace_tmp_mount:
                normalized_rw_mounts.append(f"{normalized_runtime_tmp_mount}:{DEFAULT_CONTAINER_TMP_DIR}")

        command_env_vars: list[str] = []
        if artifacts_url:
            command_env_vars.append(f"AGENT_ARTIFACTS_URL={artifacts_url}")
        if artifacts_token:
            command_env_vars.append(f"AGENT_ARTIFACT_TOKEN={artifacts_token}")

        command_env_vars.append(f"{AGENT_TOOLS_URL_ENV}={agent_tools_url}")
        command_env_vars.append(f"{AGENT_TOOLS_TOKEN_ENV}={agent_tools_token}")
        command_env_vars.append(f"{AGENT_TOOLS_PROJECT_ID_ENV}={agent_tools_project_id}")
        command_env_vars.append(f"{AGENT_TOOLS_CHAT_ID_ENV}={agent_tools_chat_id}")
        if normalized_runtime_tmp_mount:
            command_env_vars.append(f"{AGENT_HUB_TMP_HOST_PATH_ENV}={normalized_runtime_tmp_mount}")
        normalized_ready_ack_guid = str(ready_ack_guid or "").strip()
        if normalized_ready_ack_guid:
            command_env_vars.append(f"{AGENT_TOOLS_READY_ACK_GUID_ENV}={normalized_ready_ack_guid}")
        for env_entry in self._git_identity_env_vars_from_settings():
            command_env_vars.append(env_entry)

        for env_entry in env_vars or []:
            if _is_reserved_env_entry(str(env_entry)):
                continue
            if str(env_entry).split("=", 1)[0].strip() == AGENT_HUB_TMP_HOST_PATH_ENV:
                continue
            command_env_vars.append(str(env_entry))

        spec = core_launch.LaunchSpec(
            repo_root=_repo_root(),
            workspace=workspace,
            container_project_name=container_project_name,
            agent_home_path=self.host_agent_home,
            runtime_config_file=runtime_config_file,
            system_prompt_file=self.system_prompt_file,
            agent_command=agent_command,
            run_mode=str(run_mode),
            local_uid=int(runtime_uid),
            local_gid=int(runtime_gid),
            local_user=self.local_user,
            local_supplementary_gids=runtime_supp_gids,
            allocate_tty=allocate_tty,
            resume=bool(resume and normalized_agent_type == AGENT_TYPE_CODEX),
            snapshot_tag=str(snapshot_tag or ""),
            ro_mounts=tuple(normalized_ro_mounts),
            rw_mounts=tuple(normalized_rw_mounts),
            env_vars=tuple(command_env_vars),
            extra_args=tuple(str(arg) for arg in (extra_args or [])),
            openai_credentials_args=tuple(self._openai_credentials_arg()),
            base_args=tuple(project_base_args),
            setup_script=str(setup_script or ""),
            prepare_snapshot_only=prepare_snapshot_only,
            project_in_image=project_in_image,
        )
        return core_launch.compile_agent_cli_command(spec)

    def _launch_profile_from_command(
        self,
        *,
        mode: str,
        command: list[str],
        workspace: Path,
        runtime_config_file: Path,
        container_project_name: str,
        agent_type: str,
        snapshot_tag: str,
        prepare_snapshot_only: bool,
    ) -> dict[str, Any]:
        runtime_image = ""
        if snapshot_tag:
            runtime_image = str(snapshot_tag)
            if prepare_snapshot_only:
                runtime_image = str(agent_cli_image._snapshot_setup_runtime_image_for_snapshot(snapshot_tag))
        parsed = core_launch.parse_compiled_agent_cli_command(command)

        return {
            "mode": str(mode or "").strip(),
            "generated_at": _iso_now(),
            "workspace": str(workspace),
            "runtime_config_file": str(runtime_config_file),
            "container_project_name": str(container_project_name),
            "agent_type": _normalize_chat_agent_type(agent_type, strict=True),
            "snapshot_tag": str(snapshot_tag or ""),
            "runtime_image": runtime_image,
            "prepare_snapshot_only": bool(prepare_snapshot_only),
            "ro_mounts": list(parsed.ro_mounts),
            "rw_mounts": list(parsed.rw_mounts),
            "env_vars": list(parsed.env_vars),
            "container_args": list(parsed.container_args),
            "command": [str(item) for item in command],
        }

    def project_snapshot_launch_profile(self, project_id: str) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        workspace = self._ensure_project_clone(project)
        self._sync_checkout_to_remote(workspace, project)
        head_result = _run_for_repo(["rev-parse", "HEAD"], workspace, capture=True)
        project_for_launch = dict(project)
        project_for_launch["repo_head_sha"] = head_result.stdout.strip()
        snapshot_tag = self._project_setup_snapshot_tag(project_for_launch)
        resolved_project_id = str(project_for_launch.get("id") or project_id).strip()
        project_tmp_workspace = self.project_tmp_workdir(resolved_project_id)
        project_tmp_workspace.mkdir(parents=True, exist_ok=True)
        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=_container_project_name(project_for_launch.get("name") or project_for_launch.get("id")),
            runtime_config_file=self.config_file,
            agent_type=DEFAULT_CHAT_AGENT_TYPE,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=f"{self.artifact_publish_base_url}/api/projects/{resolved_project_id}/agent-tools",
            agent_tools_token="snapshot-token",
            agent_tools_project_id=resolved_project_id,
            repo_url=str(project_for_launch.get("repo_url") or ""),
            project=project_for_launch,
            snapshot_tag=snapshot_tag,
            ro_mounts=project_for_launch.get("default_ro_mounts"),
            rw_mounts=project_for_launch.get("default_rw_mounts"),
            env_vars=project_for_launch.get("default_env_vars"),
            setup_script=str(project_for_launch.get("setup_script") or ""),
            prepare_snapshot_only=True,
            project_in_image=True,
            runtime_tmp_mount=str(project_tmp_workspace),
            context_key=f"snapshot:{project_for_launch.get('id')}",
        )
        return self._launch_profile_from_command(
            mode="project_snapshot",
            command=cmd,
            workspace=workspace,
            runtime_config_file=self.config_file,
            container_project_name=_container_project_name(project_for_launch.get("name") or project_for_launch.get("id")),
            agent_type=DEFAULT_CHAT_AGENT_TYPE,
            snapshot_tag=snapshot_tag,
            prepare_snapshot_only=True,
        )

    def chat_launch_profile(
        self,
        chat_id: str,
        *,
        resume: bool = False,
        agent_tools_token: str = "agent-tools-token",
        artifact_publish_token: str = "artifact-token",
        ready_ack_guid: str = "ready-ack-guid",
    ) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat.get("project_id"))
        if project is None:
            raise HTTPException(status_code=404, detail="Parent project missing.")

        snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
        expected_snapshot_tag = self._project_setup_snapshot_tag(project)
        snapshot_ready = (
            str(project.get("build_status") or "") == "ready"
            and snapshot_tag
            and snapshot_tag == expected_snapshot_tag
        )
        if not snapshot_ready:
            raise HTTPException(status_code=409, detail="Project image is not ready yet. Wait for setup build to finish.")

        workspace = self._ensure_chat_clone(chat, project)
        self._sync_checkout_to_remote(workspace, project)
        container_project_name = _container_project_name(project.get("name") or project.get("id"))
        agent_type = _normalize_chat_agent_type(chat.get("agent_type"), strict=True)
        runtime_config_file = self._prepare_chat_runtime_config(
            chat_id,
            agent_type=agent_type,
            agent_tools_url=self._chat_agent_tools_url(chat_id),
            agent_tools_token=agent_tools_token,
            agent_tools_project_id=str(project.get("id") or ""),
            agent_tools_chat_id=chat_id,
            trusted_project_path=str(PurePosixPath(DEFAULT_CONTAINER_HOME) / container_project_name),
        )
        agent_args = [str(arg) for arg in (chat.get("agent_args") or []) if str(arg).strip()]
        if resume and agent_type == AGENT_TYPE_CODEX:
            agent_args = []
        elif resume:
            agent_args = self._resume_agent_args(agent_type, agent_args)

        project_id = str(project.get("id") or "")
        chat_tmp_workspace = self.chat_tmp_workdir(project_id, chat_id)
        chat_tmp_workspace.mkdir(parents=True, exist_ok=True)

        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=container_project_name,
            runtime_config_file=runtime_config_file,
            agent_type=agent_type,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=self._chat_agent_tools_url(chat_id),
            agent_tools_token=agent_tools_token,
            agent_tools_project_id=str(project.get("id") or ""),
            agent_tools_chat_id=chat_id,
            repo_url=str(project.get("repo_url") or ""),
            project=project,
            snapshot_tag=snapshot_tag,
            ro_mounts=chat.get("ro_mounts"),
            rw_mounts=chat.get("rw_mounts"),
            env_vars=chat.get("env_vars"),
            artifacts_url=self._chat_artifact_publish_url(chat_id),
            artifacts_token=artifact_publish_token,
            ready_ack_guid=ready_ack_guid,
            resume=resume,
            project_in_image=True,
            runtime_tmp_mount=str(chat_tmp_workspace),
            context_key=f"chat_launch_profile:{chat_id}",
            extra_args=agent_args,
        )
        return self._launch_profile_from_command(
            mode="chat_start",
            command=cmd,
            workspace=workspace,
            runtime_config_file=runtime_config_file,
            container_project_name=container_project_name,
            agent_type=agent_type,
            snapshot_tag=snapshot_tag,
            prepare_snapshot_only=False,
        )

    def _run_temporary_auto_config_chat(
        self,
        workspace: Path,
        repo_url: str,
        branch: str,
        agent_type: str = AGENT_TYPE_CODEX,
        agent_args: list[str] | None = None,
        on_output: Callable[[str], None] | None = None,
        request_id: str = "",
    ) -> dict[str, Any]:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        resolved_agent_type = _normalize_chat_agent_type(agent_type, strict=True)
        normalized_agent_args = [str(arg) for arg in (agent_args or []) if str(arg).strip()]

        def emit(chunk: str) -> None:
            if on_output is None:
                return
            text = str(chunk or "")
            if not text:
                return
            try:
                on_output(text)
            except Exception:
                LOGGER.exception("Auto-config output callback failed.")

        if resolved_agent_type == AGENT_TYPE_CODEX:
            account_connected, _ = _read_codex_auth(self.openai_codex_auth_file)
            if not account_connected:
                raise HTTPException(status_code=409, detail=AUTO_CONFIG_NOT_CONNECTED_ERROR)

        prompt = self._auto_config_prompt(repo_url, branch)
        output_file = workspace / f".agent-hub-auto-config-{uuid.uuid4().hex}.json"
        container_project_name = _container_project_name(_extract_repo_name(repo_url) or "auto-config")
        container_workspace = str(PurePosixPath(DEFAULT_CONTAINER_HOME) / container_project_name)
        container_output_file = str(PurePosixPath(container_workspace) / output_file.name)
        session_id, session_token = self._create_agent_tools_session(repo_url=repo_url, workspace=workspace)
        ready_ack_guid = self.issue_agent_tools_session_ready_ack_guid(session_id)
        agent_tools_url = f"{self.artifact_publish_base_url}/api/agent-tools/sessions/{session_id}"
        agent_tools_chat_id = f"auto-config:{session_id}"
        runtime_config_file = self._prepare_chat_runtime_config(
            f"auto-config-{session_id}",
            agent_type=resolved_agent_type,
            agent_tools_url=agent_tools_url,
            agent_tools_token=session_token,
            agent_tools_project_id="",
            agent_tools_chat_id=agent_tools_chat_id,
            trusted_project_path=container_workspace,
        )
        artifact_publish_token = _new_artifact_publish_token()
        with self._agent_tools_sessions_lock:
            active_session = self._agent_tools_sessions.get(session_id)
            if active_session is not None:
                active_session["artifact_publish_token_hash"] = _hash_artifact_publish_token(artifact_publish_token)
                self._agent_tools_sessions[session_id] = active_session

        extra_args = [
            *normalized_agent_args,
            "exec",
            "--skip-git-repo-check",
            "--cd",
            container_workspace,
            "--sandbox",
            "workspace-write",
            "--output-last-message",
            container_output_file,
            prompt,
        ]
        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=container_project_name,
            runtime_config_file=runtime_config_file,
            agent_type=resolved_agent_type,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=agent_tools_url,
            agent_tools_token=session_token,
            agent_tools_project_id="",
            agent_tools_chat_id=agent_tools_chat_id,
            repo_url=repo_url,
            artifacts_url=f"{self.artifact_publish_base_url}/api/agent-tools/sessions/{session_id}/artifacts/publish",
            artifacts_token=artifact_publish_token,
            ready_ack_guid=ready_ack_guid,
            allocate_tty=False,
            context_key=f"auto_config_chat:{session_id}",
            extra_args=extra_args,
        )
        emit("Launching temporary repository analysis chat...\n")
        emit(f"Working directory: {workspace}\n")
        emit(f"Repository URL: {repo_url}\n")
        emit(f"Branch: {branch}\n\n")

        if self._is_auto_config_request_cancelled(normalized_request_id):
            raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR)

        try:
            process = subprocess.Popen(
                cmd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                start_new_session=True,
            )
            self._set_auto_config_request_process(normalized_request_id, process)
        except OSError as exc:
            try:
                runtime_config_file.unlink()
            except OSError:
                pass
            self._remove_agent_tools_session(session_id)
            raise HTTPException(status_code=502, detail=f"Temporary auto-config chat failed to start: {exc}") from exc

        output_chunks: list[str] = []

        def consume_output() -> None:
            stdout = process.stdout
            if stdout is None:
                return
            try:
                for line in iter(stdout.readline, ""):
                    if line == "":
                        break
                    output_chunks.append(line)
                    emit(line)
            finally:
                stdout.close()

        try:
            try:
                consumer = Thread(target=consume_output, daemon=True)
                consumer.start()
                return_code = process.wait(timeout=max(20.0, float(AUTO_CONFIG_CHAT_TIMEOUT_SECONDS)))
                consumer.join(timeout=2.0)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
                emit("\nTemporary auto-config chat timed out.\n")
                if self._is_auto_config_request_cancelled(normalized_request_id):
                    raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR) from exc
                raise HTTPException(status_code=504, detail="Temporary auto-config chat timed out.") from exc

            output_text = "".join(output_chunks).strip()
            if return_code != 0:
                if self._is_auto_config_request_cancelled(normalized_request_id):
                    emit("\nAuto-config chat was cancelled by user.\n")
                    raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR)
                detail = _codex_exec_error_message_full(output_text)
                raise HTTPException(status_code=502, detail=f"Temporary auto-config chat failed: {detail}")

            try:
                raw_payload_text = output_file.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError as exc:
                raise HTTPException(status_code=502, detail=AUTO_CONFIG_MISSING_OUTPUT_ERROR) from exc
            if not raw_payload_text:
                raise HTTPException(status_code=502, detail=AUTO_CONFIG_MISSING_OUTPUT_ERROR)

            try:
                parsed_payload = _parse_json_object_from_text(raw_payload_text)
            except ValueError as exc:
                raise HTTPException(status_code=502, detail=AUTO_CONFIG_INVALID_OUTPUT_ERROR) from exc
            return {
                "payload": parsed_payload,
                "model": _auto_config_analysis_model(resolved_agent_type, normalized_agent_args),
                "agent_type": resolved_agent_type,
                "agent_args": normalized_agent_args,
            }
        finally:
            self._set_auto_config_request_process(normalized_request_id, None)
            try:
                output_file.unlink()
            except OSError:
                pass
            try:
                runtime_config_file.unlink()
            except OSError:
                pass
            self._remove_agent_tools_session(session_id)

    def auto_configure_project(
        self,
        repo_url: Any,
        default_branch: Any = None,
        request_id: Any = None,
        agent_type: Any = None,
        agent_args: Any = None,
    ) -> dict[str, Any]:
        normalized_repo_url = str(repo_url or "").strip()
        validation_error = _project_repo_url_validation_error(normalized_repo_url)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)
        resolved_agent_type = _resolve_optional_chat_agent_type(
            agent_type,
            default_value=self.default_chat_agent_type(),
        )
        if agent_args is None:
            normalized_agent_args: list[str] = []
        elif isinstance(agent_args, list):
            normalized_agent_args = [str(arg) for arg in agent_args if str(arg).strip()]
        else:
            raise HTTPException(status_code=400, detail="agent_args must be an array.")
        normalized_request_id = str(request_id or "").strip()[:AUTO_CONFIG_REQUEST_ID_MAX_CHARS]
        if normalized_request_id:
            self._register_auto_config_request(normalized_request_id)
            if self._is_auto_config_request_cancelled(normalized_request_id):
                self._clear_auto_config_request(normalized_request_id)
                raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR)

        def emit_auto_config_log(text: str, replace: bool = False) -> None:
            if not normalized_request_id:
                return
            self._emit_auto_config_log(normalized_request_id, text, replace=replace)

        requested_branch = str(default_branch or "").strip()
        git_env = self._github_git_env_for_repo(normalized_repo_url)
        sanitized_git_env = {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
        authenticated_git_env = dict(sanitized_git_env)
        authenticated_git_env.update(git_env)
        resolved_branch = requested_branch or _detect_default_branch(
            normalized_repo_url,
            env=authenticated_git_env,
        )

        emit_auto_config_log("", replace=True)
        emit_auto_config_log("Preparing repository checkout for temporary analysis chat...\n")
        emit_auto_config_log(f"Repository URL: {normalized_repo_url}\n")
        emit_auto_config_log(f"Requested branch: {requested_branch or 'auto-detect'}\n")
        emit_auto_config_log(f"Analysis agent: {resolved_agent_type}\n")
        emit_auto_config_log(
            f"Analysis model: {_auto_config_analysis_model(resolved_agent_type, normalized_agent_args)}\n"
        )

        if self._is_auto_config_request_cancelled(normalized_request_id):
            raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR)

        try:
            with tempfile.TemporaryDirectory(prefix="agent-hub-auto-config-", dir=str(self.data_dir)) as temp_dir:
                workspace = Path(temp_dir) / "repo"
                env_candidates: list[dict[str, str]] = [authenticated_git_env]
                if git_env:
                    env_candidates.append(sanitized_git_env)

                def run_clone(cmd: list[str]) -> subprocess.CompletedProcess:
                    last_result = subprocess.CompletedProcess(cmd, 1, "", "")
                    for env_candidate in env_candidates:
                        if workspace.exists():
                            self._delete_path(workspace)
                        emit_auto_config_log(f"\n$ {' '.join(cmd)}\n")
                        result = _run(cmd, capture=True, check=False, env=env_candidate)
                        command_output = ((result.stdout or "") + (result.stderr or "")).strip()
                        if command_output:
                            emit_auto_config_log(f"{command_output}\n")
                        elif result.returncode != 0:
                            emit_auto_config_log(f"Command exited with code {result.returncode}.\n")
                        if result.returncode == 0:
                            return result
                        last_result = result
                    return last_result

                clone_cmd_with_branch = [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    resolved_branch,
                    normalized_repo_url,
                    str(workspace),
                ]
                clone_result = run_clone(clone_cmd_with_branch)
                if clone_result.returncode != 0:
                    if requested_branch:
                        detail = ((clone_result.stdout or "") + (clone_result.stderr or "")).strip()
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Unable to clone repository branch '{requested_branch}'. "
                                f"{detail or 'git clone failed.'}"
                            ),
                        )

                    clone_cmd_default = ["git", "clone", "--depth", "1", normalized_repo_url, str(workspace)]
                    clone_result = run_clone(clone_cmd_default)
                    if clone_result.returncode != 0:
                        detail = ((clone_result.stdout or "") + (clone_result.stderr or "")).strip()
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unable to clone repository for auto-configure. {detail or 'git clone failed.'}",
                        )

                    head_result = _run_for_repo(
                        ["rev-parse", "--abbrev-ref", "HEAD"],
                        workspace,
                        capture=True,
                        check=False,
                        env=sanitized_git_env,
                    )
                    if head_result.returncode == 0 and head_result.stdout.strip():
                        resolved_branch = head_result.stdout.strip()

                emit_auto_config_log("\nRepository checkout complete. Starting temporary analysis chat...\n")
                if self._is_auto_config_request_cancelled(normalized_request_id):
                    raise HTTPException(status_code=409, detail=AUTO_CONFIG_CANCELLED_ERROR)

                recommendation: dict[str, Any] = {}
                chat_result: dict[str, Any] = {}
                emit_auto_config_log("Running temporary analysis chat...\n")
                chat_result = self._run_temporary_auto_config_chat(
                    workspace,
                    normalized_repo_url,
                    resolved_branch,
                    agent_type=resolved_agent_type,
                    agent_args=normalized_agent_args,
                    on_output=emit_auto_config_log if normalized_request_id else None,
                    request_id=normalized_request_id,
                )
                container_workspace = _container_workspace_path_for_project(
                    _extract_repo_name(normalized_repo_url) or "auto-config"
                )
                recommendation = self._normalize_auto_config_recommendation(
                    chat_result.get("payload") or {},
                    workspace,
                    project_container_workspace=container_workspace,
                )
                recommendation = self._apply_auto_config_repository_hints(recommendation, workspace)
                recommendation = self._normalize_auto_config_recommendation(
                    recommendation,
                    workspace,
                    project_container_workspace=container_workspace,
                )
                emit_auto_config_log("Auto-config recommendation discovery completed.\n")
        except HTTPException as exc:
            detail = str(exc.detail or f"HTTP {exc.status_code}")
            emit_auto_config_log(f"\nAuto-config failed: {detail}\n")
            raise
        finally:
            self._clear_auto_config_request(normalized_request_id)

        recommendation["default_branch"] = resolved_branch
        emit_auto_config_log("\nAuto-config completed successfully.\n")
        return recommendation

    def connect_openai(self, api_key: Any, verify: bool = True) -> dict[str, Any]:
        normalized = _normalize_openai_api_key(api_key)
        if verify:
            _verify_openai_api_key(normalized)
        _write_private_env_file(
            self.openai_credentials_file,
            f"OPENAI_API_KEY={json.dumps(normalized)}\n",
        )
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_api_key_connected")
        LOGGER.debug("OpenAI API key connected.")
        return status

    def disconnect_openai(self) -> dict[str, Any]:
        if self.openai_credentials_file.exists():
            try:
                self.openai_credentials_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to remove stored OpenAI credentials.") from exc
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_api_key_disconnected")
        LOGGER.debug("OpenAI API key disconnected.")
        return status

    def list_github_app_installations(self) -> dict[str, Any]:
        status = self.github_app_auth_status()
        if not status.get("app_configured"):
            return {
                "app_configured": False,
                "app_slug": status.get("app_slug") or "",
                "install_url": status.get("install_url") or "",
                "installations": [],
                "connected_installation_id": int(status.get("installation_id") or 0),
                "error": str(status.get("error") or ""),
            }

        _response_status, payload_text = self._github_api_request(
            "GET",
            "/app/installations?per_page=100",
            auth_mode="app",
        )
        try:
            raw_payload = json.loads(payload_text) if payload_text else []
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation list payload.") from exc
        if not isinstance(raw_payload, list):
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation list payload.")

        installations: list[dict[str, Any]] = []
        for item in raw_payload:
            if not isinstance(item, dict):
                continue
            installation_id = item.get("id")
            if not isinstance(installation_id, int) or installation_id <= 0:
                continue
            account = item.get("account")
            account_login = ""
            account_type = ""
            if isinstance(account, dict):
                account_login = str(account.get("login") or "")
                account_type = str(account.get("type") or "")
            installations.append(
                {
                    "id": installation_id,
                    "account_login": account_login,
                    "account_type": account_type,
                    "repository_selection": str(item.get("repository_selection") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                    "suspended_at": str(item.get("suspended_at") or ""),
                }
            )

        return {
            "app_configured": True,
            "app_slug": status.get("app_slug") or "",
            "install_url": status.get("install_url") or "",
            "installations": installations,
            "connected_installation_id": int(status.get("installation_id") or 0),
            "error": "",
        }

    def connect_github_app(self, installation_id: Any) -> dict[str, Any]:
        status = self.github_app_auth_status()
        if not status.get("app_configured"):
            detail = str(status.get("error") or "GitHub App is not configured on this server.")
            raise HTTPException(status_code=400, detail=detail)

        normalized_id = _normalize_github_installation_id(installation_id)
        _response_status, installation_payload_text = self._github_api_request(
            "GET",
            f"/app/installations/{normalized_id}",
            auth_mode="app",
        )
        try:
            installation_payload = json.loads(installation_payload_text) if installation_payload_text else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation payload.") from exc
        if not isinstance(installation_payload, dict):
            raise HTTPException(status_code=502, detail="GitHub API returned invalid installation payload.")

        account = installation_payload.get("account")
        account_login = ""
        account_type = ""
        if isinstance(account, dict):
            account_login = str(account.get("login") or "")
            account_type = str(account.get("type") or "")
        repository_selection = str(installation_payload.get("repository_selection") or "")

        self._clear_github_installation_state(remove_credentials=False)
        record = {
            "installation_id": normalized_id,
            "account_login": account_login,
            "account_type": account_type,
            "repository_selection": repository_selection,
            "connected_at": _iso_now(),
        }
        _write_private_env_file(self.github_app_installation_file, json.dumps(record, indent=2) + "\n")
        status = self.github_app_auth_status()
        self._emit_auth_changed(reason="github_app_connected")
        LOGGER.debug("GitHub App installation connected: id=%s account=%s", normalized_id, account_login)
        return status

    def _connect_personal_access_token(
        self,
        provider: str,
        personal_access_token: Any,
        host: Any = "",
    ) -> dict[str, Any]:
        normalized_provider = (
            GIT_PROVIDER_GITLAB if str(provider or "").strip().lower() == GIT_PROVIDER_GITLAB else GIT_PROVIDER_GITHUB
        )
        normalized_token = _normalize_github_personal_access_token(personal_access_token)
        host_candidate = str(host or "").strip()
        if not host_candidate:
            host_candidate = "gitlab.com" if normalized_provider == GIT_PROVIDER_GITLAB else self._github_provider_host()
        normalized_scheme, normalized_host = _normalize_github_credential_endpoint(
            host_candidate,
            field_name="host",
            default_scheme=GIT_CREDENTIAL_DEFAULT_SCHEME,
        )
        verification = self._verify_github_personal_access_token(
            normalized_token,
            normalized_host,
            normalized_scheme,
        )
        verified_provider = str(verification.get("provider") or "").strip().lower()
        if verified_provider != normalized_provider:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Connected token resolved to provider '{verified_provider or 'unknown'}', "
                    f"but this endpoint expects '{normalized_provider}'."
                ),
            )
        account_login = verification["account_login"]

        account_name = str(verification.get("account_name") or account_login).strip() or account_login
        account_email = str(verification.get("account_email") or "").strip()
        account_id = str(verification.get("account_id") or "").strip()
        connected_at = _iso_now()
        record = {
            "token_id": uuid.uuid4().hex,
            "host": normalized_host,
            "scheme": normalized_scheme,
            "provider": normalized_provider,
            "personal_access_token": normalized_token,
            "account_login": account_login,
            "account_name": account_name,
            "account_email": account_email,
            "account_id": account_id,
            "git_user_name": account_name,
            "git_user_email": account_email,
            "token_scopes": verification.get("token_scopes") or "",
            "verified_at": connected_at,
            "connected_at": connected_at,
        }

        existing = self._connected_personal_access_tokens(normalized_provider)
        filtered_existing: list[dict[str, Any]] = []
        for existing_record in existing:
            existing_host = str(existing_record.get("host") or "").strip().lower()
            try:
                existing_scheme = _normalize_github_credential_scheme(
                    existing_record.get("scheme"),
                    field_name="scheme",
                )
            except HTTPException:
                existing_scheme = GIT_CREDENTIAL_DEFAULT_SCHEME
            existing_login = str(existing_record.get("account_login") or "").strip().lower()
            existing_token = str(existing_record.get("personal_access_token") or "").strip()
            if (
                existing_host == normalized_host
                and existing_scheme == normalized_scheme
                and existing_login == account_login.lower()
                and existing_token == normalized_token
            ):
                continue
            filtered_existing.append(existing_record)

        self._persist_personal_access_tokens([record, *filtered_existing], normalized_provider)
        status = (
            self.gitlab_tokens_status()
            if normalized_provider == GIT_PROVIDER_GITLAB
            else self.github_tokens_status()
        )
        self._emit_auth_changed(reason=f"{normalized_provider}_personal_access_token_connected")
        LOGGER.debug(
            "Personal access token connected: provider=%s host=%s account=%s",
            normalized_provider,
            normalized_host,
            account_login,
        )
        return status

    def connect_github_personal_access_token(
        self,
        personal_access_token: Any,
        host: Any = "",
    ) -> dict[str, Any]:
        return self._connect_personal_access_token(
            GIT_PROVIDER_GITHUB,
            personal_access_token=personal_access_token,
            host=host,
        )

    def connect_gitlab_personal_access_token(
        self,
        personal_access_token: Any,
        host: Any = "",
    ) -> dict[str, Any]:
        return self._connect_personal_access_token(
            GIT_PROVIDER_GITLAB,
            personal_access_token=personal_access_token,
            host=host,
        )

    def _disconnect_personal_access_token(self, provider: str, token_id: Any) -> dict[str, Any]:
        normalized_provider = (
            GIT_PROVIDER_GITLAB if str(provider or "").strip().lower() == GIT_PROVIDER_GITLAB else GIT_PROVIDER_GITHUB
        )
        normalized_token_id = str(token_id or "").strip()
        if not normalized_token_id:
            raise HTTPException(status_code=400, detail="token_id is required.")
        if len(normalized_token_id) > GITHUB_PERSONAL_ACCESS_TOKEN_ID_MAX_CHARS:
            raise HTTPException(status_code=400, detail="token_id is invalid.")

        existing = self._connected_personal_access_tokens(normalized_provider)
        remaining = [record for record in existing if str(record.get("token_id") or "").strip() != normalized_token_id]
        if len(remaining) == len(existing):
            raise HTTPException(status_code=404, detail=f"{normalized_provider.capitalize()} personal access token not found.")

        self._persist_personal_access_tokens(remaining, normalized_provider)

        status = (
            self.gitlab_tokens_status()
            if normalized_provider == GIT_PROVIDER_GITLAB
            else self.github_tokens_status()
        )
        self._emit_auth_changed(reason=f"{normalized_provider}_personal_access_token_disconnected")
        LOGGER.debug(
            "Personal access token disconnected: provider=%s token_id=%s remaining=%s",
            normalized_provider,
            normalized_token_id,
            len(remaining),
        )
        return status

    def disconnect_github_personal_access_token(self, token_id: Any) -> dict[str, Any]:
        return self._disconnect_personal_access_token(GIT_PROVIDER_GITHUB, token_id)

    def disconnect_gitlab_personal_access_token(self, token_id: Any) -> dict[str, Any]:
        return self._disconnect_personal_access_token(GIT_PROVIDER_GITLAB, token_id)

    def _disconnect_all_personal_access_tokens(self, provider: str) -> dict[str, Any]:
        normalized_provider = (
            GIT_PROVIDER_GITLAB if str(provider or "").strip().lower() == GIT_PROVIDER_GITLAB else GIT_PROVIDER_GITHUB
        )
        self._clear_personal_access_token_state(normalized_provider, remove_credentials=False)
        status = (
            self.gitlab_tokens_status()
            if normalized_provider == GIT_PROVIDER_GITLAB
            else self.github_tokens_status()
        )
        self._emit_auth_changed(reason=f"{normalized_provider}_personal_access_tokens_disconnected")
        LOGGER.debug("All personal access tokens disconnected for provider=%s", normalized_provider)
        return status

    def disconnect_github_personal_access_tokens(self) -> dict[str, Any]:
        return self._disconnect_all_personal_access_tokens(GIT_PROVIDER_GITHUB)

    def disconnect_gitlab_personal_access_tokens(self) -> dict[str, Any]:
        return self._disconnect_all_personal_access_tokens(GIT_PROVIDER_GITLAB)

    def disconnect_github_app(self) -> dict[str, Any]:
        self._clear_github_installation_state(remove_credentials=False)
        status = self.github_app_auth_status()
        self._emit_auth_changed(reason="github_app_disconnected")
        LOGGER.debug("GitHub App installation disconnected.")
        return status

    def disconnect_openai_account(self) -> dict[str, Any]:
        self.cancel_openai_account_login()
        if self.openai_codex_auth_file.exists():
            try:
                self.openai_codex_auth_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to remove stored OpenAI account credentials.") from exc
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_account_disconnected")
        self._emit_openai_account_session_changed(reason="openai_account_disconnected")
        LOGGER.debug("OpenAI account disconnected.")
        return status

    def _openai_login_session_payload(self, session: OpenAIAccountLoginSession | None) -> dict[str, Any] | None:
        if session is None:
            return None
        running = _is_process_running(session.process.pid) and session.exit_code is None
        return {
            "id": session.id,
            "method": session.method,
            "status": session.status,
            "started_at": session.started_at,
            "completed_at": session.completed_at,
            "exit_code": session.exit_code,
            "error": session.error,
            "running": running,
            "login_url": session.login_url,
            "device_code": session.device_code,
            "local_callback_url": session.local_callback_url,
            "callback_port": session.callback_port,
            "callback_path": session.callback_path,
            "log_tail": session.log_tail,
        }

    def openai_account_session_payload(self) -> dict[str, Any]:
        with self._openai_login_lock:
            session_payload = self._openai_login_session_payload(self._openai_login_session)
        account_payload = self._openai_account_payload()
        return {
            "session": session_payload,
            "account_connected": account_payload["account_connected"],
            "account_auth_mode": account_payload["account_auth_mode"],
            "account_updated_at": account_payload["account_updated_at"],
        }

    def _openai_login_container_cmd(self, container_name: str, method: str) -> list[str]:
        container_home = DEFAULT_CONTAINER_HOME
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--init",
            "--user",
            f"{self.local_uid}:{self.local_gid}",
            "--network",
            "host",
            "--workdir",
            container_home,
            "--tmpfs",
            TMP_DIR_TMPFS_SPEC,
            "--volume",
            f"{self.host_codex_dir}:{container_home}/.codex",
            "--volume",
            f"{self.config_file}:{container_home}/.codex/config.toml",
            "--env",
            f"LOCAL_UMASK={self.local_umask}",
            "--env",
            f"LOCAL_USER={self.local_user}",
            "--env",
            f"HOME={container_home}",
            "--env",
            f"CONTAINER_HOME={container_home}",
            "--env",
            f"PATH={container_home}/.codex/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        ]
        cmd.extend(["--group-add", "agent"])
        for supp_gid in _parse_gid_csv(self.local_supp_gids):
            if supp_gid == self.local_gid:
                continue
            cmd.extend(["--group-add", str(supp_gid)])
        cmd.extend(
            [
                DEFAULT_AGENT_IMAGE,
                "codex",
                "login",
            ]
        )
        if method == "device_auth":
            cmd.append("--device-auth")
        return cmd

    def _start_openai_login_reader(self, session_id: str) -> None:
        thread = Thread(target=self._openai_login_reader_loop, args=(session_id,), daemon=True)
        thread.start()

    def _openai_login_reader_loop(self, session_id: str) -> None:
        with self._openai_login_lock:
            session = self._openai_login_session
            if session is None or session.id != session_id:
                return
            process = session.process

        stdout = process.stdout
        if stdout is not None:
            for raw_line in iter(stdout.readline, ""):
                if raw_line == "":
                    break
                clean_line = ANSI_ESCAPE_RE.sub("", raw_line).replace("\r", "")
                should_emit_session = False
                with self._openai_login_lock:
                    current = self._openai_login_session
                    if current is None or current.id != session_id:
                        break
                    current.log_tail = _append_tail(
                        current.log_tail,
                        clean_line,
                        OPENAI_ACCOUNT_LOGIN_LOG_MAX_CHARS,
                    )

                    callback_candidate = _first_url_in_text(clean_line, "http://localhost")
                    if callback_candidate:
                        local_url, callback_port, callback_path = _parse_local_callback(callback_candidate)
                        if local_url:
                            current.local_callback_url = local_url
                            current.callback_port = callback_port
                            current.callback_path = callback_path

                    login_url = _openai_login_url_in_text(clean_line)
                    if login_url:
                        current.login_url = login_url
                        if current.method == "browser_callback" and current.status in {"starting", "running"}:
                            current.status = "waiting_for_browser"
                        parsed_login = urllib.parse.urlparse(login_url)
                        query = urllib.parse.parse_qs(parsed_login.query)
                        redirect_values = query.get("redirect_uri") or []
                        if redirect_values:
                            local_url, callback_port, callback_path = _parse_local_callback(redirect_values[0])
                            if local_url:
                                current.local_callback_url = local_url
                                current.callback_port = callback_port
                                current.callback_path = callback_path

                    device_code_match = re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{5}\b", clean_line)
                    if device_code_match:
                        current.device_code = device_code_match.group(0)
                        if current.method == "device_auth" and current.status in {"starting", "running", "waiting_for_browser"}:
                            current.status = "waiting_for_device_code"
                    should_emit_session = True
                if should_emit_session:
                    self._emit_openai_account_session_changed(reason="login_output")

        exit_code = process.wait()
        should_emit_auth = False
        with self._openai_login_lock:
            current = self._openai_login_session
            if current is None or current.id != session_id:
                return
            current.exit_code = exit_code
            if not current.completed_at:
                current.completed_at = _iso_now()
            if current.status == "cancelled":
                return

            account_connected, _ = _read_codex_auth(self.openai_codex_auth_file)
            if exit_code == 0 and account_connected:
                current.status = "connected"
                current.error = ""
                should_emit_auth = True
            else:
                current.status = "failed"
                if not current.error:
                    if exit_code == 0:
                        current.error = "Login exited without saving ChatGPT account credentials."
                    else:
                        current.error = f"Login process exited with code {exit_code}."
        self._emit_openai_account_session_changed(reason="login_process_exit")
        if should_emit_auth:
            self._emit_auth_changed(reason="openai_account_connected")

    def _stop_openai_login_process(self, session: OpenAIAccountLoginSession) -> None:
        if _is_process_running(session.process.pid):
            _stop_process(session.process.pid)
        try:
            subprocess.run(
                ["docker", "rm", "-f", session.container_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return

    def start_openai_account_login(self, method: str = "browser_callback") -> dict[str, Any]:
        normalized_method = _normalize_openai_account_login_method(method)
        LOGGER.debug("Starting OpenAI account login flow method=%s.", normalized_method)
        if shutil.which("docker") is None:
            raise HTTPException(status_code=400, detail="docker command not found in PATH.")
        if not _docker_image_exists(DEFAULT_AGENT_IMAGE):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Runtime image '{DEFAULT_AGENT_IMAGE}' is not available. "
                    "Start a chat once to build it, then retry account login."
                ),
            )

        with self._openai_login_lock:
            existing = self._openai_login_session
            existing_running = bool(existing and _is_process_running(existing.process.pid))
            should_cancel_existing = bool(existing_running and existing and existing.method != normalized_method)
        if should_cancel_existing:
            self.cancel_openai_account_login()

        existing_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            existing = self._openai_login_session
            if existing is not None and _is_process_running(existing.process.pid):
                existing_payload = self._openai_login_session_payload(existing)
            else:
                container_name = f"agent-hub-openai-login-{uuid.uuid4().hex[:12]}"
                cmd = self._openai_login_container_cmd(container_name, normalized_method)
                try:
                    process = subprocess.Popen(
                        cmd,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        bufsize=1,
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise HTTPException(status_code=500, detail=f"Failed to start account login container: {exc}") from exc

                session = OpenAIAccountLoginSession(
                    id=uuid.uuid4().hex,
                    process=process,
                    container_name=container_name,
                    started_at=_iso_now(),
                    method=normalized_method,
                    status="running",
                )
                self._openai_login_session = session

        if existing_payload is not None:
            self._emit_openai_account_session_changed(reason="login_already_running")
            return {"session": existing_payload}

        self._start_openai_login_reader(session.id)
        self._emit_openai_account_session_changed(reason="login_started")
        return {"session": self._openai_login_session_payload(session)}

    def cancel_openai_account_login(self) -> dict[str, Any]:
        not_running_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            session = self._openai_login_session
            if session is None:
                return {"session": None}
            if not _is_process_running(session.process.pid):
                not_running_payload = self._openai_login_session_payload(session)
            else:
                session.status = "cancelled"
                session.error = "Cancelled by user."
                session.completed_at = _iso_now()
        if not_running_payload is not None:
            self._emit_openai_account_session_changed(reason="login_not_running")
            return {"session": not_running_payload}

        self._stop_openai_login_process(session)

        cancelled_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            current = self._openai_login_session
            if current is not None and current.id == session.id:
                current.exit_code = current.process.poll()
                cancelled_payload = self._openai_login_session_payload(current)
        if cancelled_payload is not None:
            self._emit_openai_account_session_changed(reason="login_cancelled")
            return {"session": cancelled_payload}
        return {"session": None}

    def forward_openai_account_callback(
        self,
        query: str,
        path: str = "/auth/callback",
        request_host: str = "",
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()

        with self._openai_login_lock:
            session = self._openai_login_session
            if session is None:
                raise HTTPException(status_code=409, detail="No active OpenAI account login session.")
            if session.method != "browser_callback":
                raise HTTPException(status_code=409, detail="Callback forwarding is only available for browser callback login.")
            callback_port = int(session.callback_port or OPENAI_ACCOUNT_LOGIN_DEFAULT_CALLBACK_PORT)
            callback_path = str(path or session.callback_path or "/auth/callback").strip() or "/auth/callback"
            if not callback_path.startswith("/"):
                callback_path = f"/{callback_path}"

        if not query:
            raise HTTPException(status_code=400, detail="Missing callback query parameters.")
        callback_result = self.auth_service.forward_openai_account_callback(
            session=session,
            callback_port=callback_port,
            callback_path=callback_path,
            query=query,
            artifact_publish_base_url=self.artifact_publish_base_url,
            request_host=request_host,
            request_context=request_context,
            discover_bridge_hosts=_discover_openai_callback_bridge_hosts,
            normalize_host=_normalize_callback_forward_host,
            callback_query_summary=_openai_callback_query_summary,
            redact_url_query_values=_redact_url_query_values,
            host_port_netloc=_host_port_netloc,
            classify_callback_error=_classify_openai_callback_forward_error,
            logger=LOGGER,
        )

        with self._openai_login_lock:
            current = self._openai_login_session
            if current is not None and current.id == session.id:
                current.log_tail = _append_tail(
                    current.log_tail,
                    "\n[hub] OAuth callback forwarded to local login server.\n",
                    OPENAI_ACCOUNT_LOGIN_LOG_MAX_CHARS,
                )
                if current.status in {"running", "waiting_for_browser"}:
                    current.status = "callback_received"
        self._emit_openai_account_session_changed(reason="oauth_callback_forwarded")
        LOGGER.info(
            (
                "OpenAI callback forward completed session_id=%s target_origin=%s target_path=%s "
                "status=%s response_summary_present=%s"
            ),
            session.id,
            callback_result.target_origin,
            callback_path,
            callback_result.status_code,
            bool(callback_result.response_body),
            extra={
                "component": "auth",
                "operation": "openai_callback_forward",
                "result": "completed",
                "request_id": "",
                "project_id": "",
                "chat_id": "",
                "duration_ms": max(0, int((time.monotonic() - started_at) * 1000)),
                "error_class": "none",
            },
        )

        return {
            "forwarded": True,
            "status_code": callback_result.status_code,
            "target_origin": callback_result.target_origin,
            "target_path": callback_path,
            "response_summary": _short_summary(
                ANSI_ESCAPE_RE.sub("", callback_result.response_body),
                max_words=28,
                max_chars=220,
            ),
        }


def _sync_server_globals() -> None:
    globals().update(_hub_server.__dict__)


def _wrap_sync(fn):
    def _wrapped(*args, **kwargs):
        _sync_server_globals()
        return fn(*args, **kwargs)

    _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
    _wrapped.__qualname__ = getattr(fn, "__qualname__", _wrapped.__name__)
    _wrapped.__doc__ = getattr(fn, "__doc__", None)
    return _wrapped


for _name, _member in list(HubStateOpsMixin.__dict__.items()):
    if _name.startswith("__"):
        continue
    if isinstance(_member, staticmethod):
        _fn = _member.__func__
        setattr(HubStateOpsMixin, _name, staticmethod(_wrap_sync(_fn)))
        continue
    if isinstance(_member, classmethod):
        _fn = _member.__func__
        setattr(HubStateOpsMixin, _name, classmethod(_wrap_sync(_fn)))
        continue
    if callable(_member):
        setattr(HubStateOpsMixin, _name, _wrap_sync(_member))
