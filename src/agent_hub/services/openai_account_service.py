from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path
from threading import Thread
from typing import Any, Callable

from fastapi import HTTPException

from agent_core.errors import NetworkReachabilityError


class OpenAIAccountService:
    def __init__(
        self,
        *,
        openai_codex_auth_file: Path,
        openai_credentials_file: Path,
        host_agent_home: Path,
        host_codex_dir: Path,
        config_file: Path,
        local_uid_getter: Callable[[], int],
        local_gid_getter: Callable[[], int],
        local_supp_gids_getter: Callable[[], str],
        local_user_getter: Callable[[], str],
        local_umask_getter: Callable[[], str],
        artifact_publish_base_url_getter: Callable[[], str],
        openai_login_lock: Any,
        get_openai_login_session: Callable[[], Any],
        set_openai_login_session: Callable[[Any], None],
        openai_login_session_type: type,
        emit_auth_changed: Callable[..., None],
        emit_openai_account_session_changed: Callable[..., None],
        auth_forward_openai_account_callback_fn: Callable[..., Any],
        forward_openai_callback_via_container_loopback_fn: Callable[..., Any],
        logger: Any,
        default_agent_image: str,
        openai_account_login_default_callback_port: int,
        openai_account_login_log_max_chars: int,
        ansi_escape_re: re.Pattern[str],
        tmp_dir_tmpfs_spec: str,
        default_container_home: str,
        is_process_running: Callable[[int], bool],
        stop_process: Callable[[int], None],
        parse_gid_csv: Callable[[str], list[int]],
        iso_now: Callable[[], str],
        normalize_openai_account_login_method: Callable[[Any], str],
        docker_image_exists: Callable[[str], bool],
        discover_bridge_hosts: Callable[[], tuple[list[str], dict[str, Any]]],
        normalize_callback_forward_host: Callable[[Any], str],
        openai_callback_query_summary: Callable[[str], dict[str, Any]],
        redact_url_query_values: Callable[[str], str],
        host_port_netloc: Callable[[str, int], str],
        classify_callback_error: Callable[[BaseException], str],
        append_tail: Callable[[str, str, int], str],
        short_summary: Callable[[str, int, int], str],
        first_url_in_text: Callable[[str, str], str],
        parse_local_callback: Callable[[str], tuple[str, int, str]],
        openai_login_url_in_text: Callable[[str], str],
        read_codex_auth: Callable[[Any], tuple[bool, str]],
        read_openai_api_key: Callable[[Any], str | None],
        mask_secret: Callable[[str], str],
        iso_from_timestamp: Callable[[float], str],
        normalize_openai_api_key: Callable[[Any], str],
        verify_openai_api_key: Callable[[str], None],
        write_private_env_file: Callable[[Any, str], None],
        openai_generate_chat_title: Callable[..., str],
        codex_generate_chat_title: Callable[..., str],
        chat_title_openai_model: str,
        chat_title_account_model: str,
        chat_title_auth_mode_account: str,
        chat_title_auth_mode_api_key: str,
        chat_title_auth_mode_none: str,
        chat_title_no_credentials_error: str,
        chat_title_max_chars: int,
    ) -> None:
        self._openai_codex_auth_file = openai_codex_auth_file
        self._openai_credentials_file = openai_credentials_file
        self._host_agent_home = host_agent_home
        self._host_codex_dir = host_codex_dir
        self._config_file = config_file
        self._local_uid_getter = local_uid_getter
        self._local_gid_getter = local_gid_getter
        self._local_supp_gids_getter = local_supp_gids_getter
        self._local_user_getter = local_user_getter
        self._local_umask_getter = local_umask_getter
        self._artifact_publish_base_url_getter = artifact_publish_base_url_getter
        self._openai_login_lock = openai_login_lock
        self._get_openai_login_session = get_openai_login_session
        self._set_openai_login_session = set_openai_login_session
        self._openai_login_session_type = openai_login_session_type
        self._emit_auth_changed = emit_auth_changed
        self._emit_openai_account_session_changed = emit_openai_account_session_changed
        self._auth_forward_openai_account_callback_fn = auth_forward_openai_account_callback_fn
        self._forward_openai_callback_via_container_loopback_fn = forward_openai_callback_via_container_loopback_fn
        self._logger = logger
        self._default_agent_image = str(default_agent_image)
        self._openai_account_login_default_callback_port = int(openai_account_login_default_callback_port)
        self._openai_account_login_log_max_chars = int(openai_account_login_log_max_chars)
        self._ansi_escape_re = ansi_escape_re
        self._tmp_dir_tmpfs_spec = str(tmp_dir_tmpfs_spec)
        self._default_container_home = str(default_container_home)
        self._is_process_running = is_process_running
        self._stop_process = stop_process
        self._parse_gid_csv = parse_gid_csv
        self._iso_now = iso_now
        self._normalize_openai_account_login_method = normalize_openai_account_login_method
        self._docker_image_exists = docker_image_exists
        self._discover_bridge_hosts = discover_bridge_hosts
        self._normalize_callback_forward_host = normalize_callback_forward_host
        self._openai_callback_query_summary = openai_callback_query_summary
        self._redact_url_query_values = redact_url_query_values
        self._host_port_netloc = host_port_netloc
        self._classify_callback_error = classify_callback_error
        self._append_tail = append_tail
        self._short_summary = short_summary
        self._first_url_in_text = first_url_in_text
        self._parse_local_callback = parse_local_callback
        self._openai_login_url_in_text = openai_login_url_in_text
        self._read_codex_auth = read_codex_auth
        self._read_openai_api_key = read_openai_api_key
        self._mask_secret = mask_secret
        self._iso_from_timestamp = iso_from_timestamp
        self._normalize_openai_api_key = normalize_openai_api_key
        self._verify_openai_api_key = verify_openai_api_key
        self._write_private_env_file = write_private_env_file
        self._openai_generate_chat_title = openai_generate_chat_title
        self._codex_generate_chat_title = codex_generate_chat_title
        self._chat_title_openai_model = str(chat_title_openai_model)
        self._chat_title_account_model = str(chat_title_account_model)
        self._chat_title_auth_mode_account = str(chat_title_auth_mode_account)
        self._chat_title_auth_mode_api_key = str(chat_title_auth_mode_api_key)
        self._chat_title_auth_mode_none = str(chat_title_auth_mode_none)
        self._chat_title_no_credentials_error = str(chat_title_no_credentials_error)
        self._chat_title_max_chars = int(chat_title_max_chars)

    def openai_account_payload(self) -> dict[str, Any]:
        account_connected, auth_mode = self._read_codex_auth(self._openai_codex_auth_file)
        updated_at = ""
        if self._openai_codex_auth_file.exists():
            try:
                updated_at = self._iso_from_timestamp(self._openai_codex_auth_file.stat().st_mtime)
            except OSError:
                updated_at = ""
        return {
            "account_connected": account_connected,
            "account_auth_mode": auth_mode,
            "account_updated_at": updated_at,
        }

    def openai_auth_status(self) -> dict[str, Any]:
        api_key = self._read_openai_api_key(self._openai_credentials_file)
        updated_at = ""
        if self._openai_credentials_file.exists():
            try:
                updated_at = self._iso_from_timestamp(self._openai_credentials_file.stat().st_mtime)
            except OSError:
                updated_at = ""
        account_payload = self.openai_account_payload()
        return {
            "provider": "openai",
            "connected": bool(api_key),
            "key_hint": self._mask_secret(api_key) if api_key else "",
            "updated_at": updated_at,
            "account_connected": account_payload["account_connected"],
            "account_auth_mode": account_payload["account_auth_mode"],
            "account_updated_at": account_payload["account_updated_at"],
        }

    def connect_openai(self, api_key: Any, verify: bool = True) -> dict[str, Any]:
        normalized = self._normalize_openai_api_key(api_key)
        if verify:
            self._verify_openai_api_key(normalized)
        self._write_private_env_file(
            self._openai_credentials_file,
            f"OPENAI_API_KEY={json.dumps(normalized)}\n",
        )
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_api_key_connected")
        self._logger.debug("OpenAI API key connected.")
        return status

    def disconnect_openai(self) -> dict[str, Any]:
        if self._openai_credentials_file.exists():
            try:
                self._openai_credentials_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to remove stored OpenAI credentials.") from exc
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_api_key_disconnected")
        self._logger.debug("OpenAI API key disconnected.")
        return status

    def chat_title_generation_auth(self) -> tuple[str, str]:
        account_connected, _ = self._read_codex_auth(self._openai_codex_auth_file)
        if account_connected:
            return self._chat_title_auth_mode_account, ""
        api_key = self._read_openai_api_key(self._openai_credentials_file) or ""
        if api_key:
            return self._chat_title_auth_mode_api_key, api_key
        return self._chat_title_auth_mode_none, ""

    def generate_chat_title_with_resolved_auth(
        self,
        auth_mode: str,
        api_key: str,
        user_prompts: list[str],
    ) -> tuple[str, str]:
        if auth_mode == self._chat_title_auth_mode_account:
            title = self._codex_generate_chat_title(
                host_agent_home=self._host_agent_home,
                host_codex_dir=self._host_codex_dir,
                user_prompts=user_prompts,
                max_chars=self._chat_title_max_chars,
            )
            return title, self._chat_title_account_model
        if auth_mode == self._chat_title_auth_mode_api_key:
            title = self._openai_generate_chat_title(
                api_key=api_key,
                user_prompts=user_prompts,
                max_chars=self._chat_title_max_chars,
            )
            return title, self._chat_title_openai_model
        raise RuntimeError(self._chat_title_no_credentials_error)

    def test_openai_chat_title_generation(self, prompt: Any) -> dict[str, Any]:
        submitted = " ".join(str(prompt or "").split()).strip()
        if not submitted:
            raise HTTPException(status_code=400, detail="prompt is required.")

        auth_status = self.openai_auth_status()
        auth_mode, api_key = self.chat_title_generation_auth()
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
            self._chat_title_openai_model
            if auth_mode == self._chat_title_auth_mode_api_key
            else self._chat_title_account_model
            if auth_mode == self._chat_title_auth_mode_account
            else ""
        )
        if auth_mode == self._chat_title_auth_mode_none:
            error = self._chat_title_no_credentials_error
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
            resolved_title, model = self.generate_chat_title_with_resolved_auth(
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

    def openai_login_session_payload(self, session: Any) -> dict[str, Any] | None:
        if session is None:
            return None
        running = self._is_process_running(session.process.pid) and session.exit_code is None
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

    def start_openai_login_reader(self, session_id: str) -> None:
        thread = Thread(target=self.openai_login_reader_loop, args=(session_id,), daemon=True)
        thread.start()

    def openai_login_reader_loop(self, session_id: str) -> None:
        with self._openai_login_lock:
            session = self._get_openai_login_session()
            if session is None or session.id != session_id:
                return
            process = session.process

        stdout = process.stdout
        if stdout is not None:
            for raw_line in iter(stdout.readline, ""):
                if raw_line == "":
                    break
                clean_line = self._ansi_escape_re.sub("", raw_line).replace("\r", "")
                should_emit_session = False
                with self._openai_login_lock:
                    current = self._get_openai_login_session()
                    if current is None or current.id != session_id:
                        break
                    current.log_tail = self._append_tail(
                        current.log_tail,
                        clean_line,
                        self._openai_account_login_log_max_chars,
                    )

                    callback_candidate = self._first_url_in_text(clean_line, "http://localhost")
                    if callback_candidate:
                        local_url, callback_port, callback_path = self._parse_local_callback(callback_candidate)
                        if local_url:
                            current.local_callback_url = local_url
                            current.callback_port = callback_port
                            current.callback_path = callback_path

                    login_url = self._openai_login_url_in_text(clean_line)
                    if login_url:
                        current.login_url = login_url
                        if current.method == "browser_callback" and current.status in {"starting", "running"}:
                            current.status = "waiting_for_browser"
                        parsed_login = urllib.parse.urlparse(login_url)
                        query = urllib.parse.parse_qs(parsed_login.query)
                        redirect_values = query.get("redirect_uri") or []
                        if redirect_values:
                            local_url, callback_port, callback_path = self._parse_local_callback(redirect_values[0])
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
            current = self._get_openai_login_session()
            if current is None or current.id != session_id:
                return
            current.exit_code = exit_code
            if not current.completed_at:
                current.completed_at = self._iso_now()
            if current.status == "cancelled":
                return

            account_connected, _ = self._read_codex_auth(self._openai_codex_auth_file)
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

    def stop_openai_login_process(self, session: Any) -> None:
        if self._is_process_running(session.process.pid):
            self._stop_process(session.process.pid)
        try:
            subprocess.run(
                ["docker", "rm", "-f", session.container_name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return

    def disconnect_openai_account(self) -> dict[str, Any]:
        self.cancel_openai_account_login()
        if self._openai_codex_auth_file.exists():
            try:
                self._openai_codex_auth_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Failed to remove stored OpenAI account credentials.") from exc
        status = self.openai_auth_status()
        self._emit_auth_changed(reason="openai_account_disconnected")
        self._emit_openai_account_session_changed(reason="openai_account_disconnected")
        self._logger.debug("OpenAI account disconnected.")
        return status

    def openai_account_session_payload(self) -> dict[str, Any]:
        with self._openai_login_lock:
            session_payload = self.openai_login_session_payload(self._get_openai_login_session())
        account_payload = self.openai_account_payload()
        return {
            "session": session_payload,
            "account_connected": account_payload["account_connected"],
            "account_auth_mode": account_payload["account_auth_mode"],
            "account_updated_at": account_payload["account_updated_at"],
        }

    def _openai_login_container_cmd(self, container_name: str, method: str) -> list[str]:
        container_home = self._default_container_home
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--init",
            "--user",
            f"{self._local_uid_getter()}:{self._local_gid_getter()}",
            "--network",
            "host",
            "--workdir",
            container_home,
            "--tmpfs",
            self._tmp_dir_tmpfs_spec,
            "--volume",
            f"{self._host_codex_dir}:{container_home}/.codex",
            "--volume",
            f"{self._config_file}:{container_home}/.codex/config.toml",
            "--env",
            f"LOCAL_UMASK={self._local_umask_getter()}",
            "--env",
            f"LOCAL_USER={self._local_user_getter()}",
            "--env",
            f"HOME={container_home}",
            "--env",
            f"CONTAINER_HOME={container_home}",
            "--env",
            f"PATH={container_home}/.codex/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        ]
        cmd.extend(["--group-add", "agent"])
        local_gid = self._local_gid_getter()
        for supp_gid in self._parse_gid_csv(self._local_supp_gids_getter()):
            if supp_gid == local_gid:
                continue
            cmd.extend(["--group-add", str(supp_gid)])
        cmd.extend(
            [
                self._default_agent_image,
                "codex",
                "login",
            ]
        )
        if method == "device_auth":
            cmd.append("--device-auth")
        return cmd

    def start_openai_account_login(self, method: str = "browser_callback") -> dict[str, Any]:
        normalized_method = self._normalize_openai_account_login_method(method)
        self._logger.debug("Starting OpenAI account login flow method=%s.", normalized_method)
        if shutil.which("docker") is None:
            raise HTTPException(status_code=400, detail="docker command not found in PATH.")
        if not self._docker_image_exists(self._default_agent_image):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Runtime image '{self._default_agent_image}' is not available. "
                    "Start a chat once to build it, then retry account login."
                ),
            )

        with self._openai_login_lock:
            existing = self._get_openai_login_session()
            existing_running = bool(existing and self._is_process_running(existing.process.pid))
            should_cancel_existing = bool(existing_running and existing and existing.method != normalized_method)
        if should_cancel_existing:
            self.cancel_openai_account_login()

        existing_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            existing = self._get_openai_login_session()
            if existing is not None and self._is_process_running(existing.process.pid):
                existing_payload = self.openai_login_session_payload(existing)
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

                session = self._openai_login_session_type(
                    id=uuid.uuid4().hex,
                    process=process,
                    container_name=container_name,
                    started_at=self._iso_now(),
                    method=normalized_method,
                    status="running",
                )
                self._set_openai_login_session(session)

        if existing_payload is not None:
            self._emit_openai_account_session_changed(reason="login_already_running")
            return {"session": existing_payload}

        self.start_openai_login_reader(session.id)
        self._emit_openai_account_session_changed(reason="login_started")
        return {"session": self.openai_login_session_payload(session)}

    def cancel_openai_account_login(self) -> dict[str, Any]:
        not_running_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            session = self._get_openai_login_session()
            if session is None:
                return {"session": None}
            if not self._is_process_running(session.process.pid):
                not_running_payload = self.openai_login_session_payload(session)
            else:
                session.status = "cancelled"
                session.error = "Cancelled by user."
                session.completed_at = self._iso_now()
        if not_running_payload is not None:
            self._emit_openai_account_session_changed(reason="login_not_running")
            return {"session": not_running_payload}

        self.stop_openai_login_process(session)

        cancelled_payload: dict[str, Any] | None = None
        with self._openai_login_lock:
            current = self._get_openai_login_session()
            if current is not None and current.id == session.id:
                current.exit_code = current.process.poll()
                cancelled_payload = self.openai_login_session_payload(current)
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
            session = self._get_openai_login_session()
            if session is None:
                raise HTTPException(status_code=409, detail="No active OpenAI account login session.")
            if session.method != "browser_callback":
                raise HTTPException(status_code=409, detail="Callback forwarding is only available for browser callback login.")
            try:
                callback_port = int(session.callback_port)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=409, detail="OpenAI login session has invalid callback_port.") from exc
            if callback_port < 1 or callback_port > 65535:
                raise HTTPException(status_code=409, detail="OpenAI login session callback_port is out of range.")
            session_callback_path = str(session.callback_path or "").strip()
            if not session_callback_path or not session_callback_path.startswith("/"):
                raise HTTPException(status_code=409, detail="OpenAI login session has invalid callback_path.")
            callback_path = str(path or session_callback_path).strip()
            if not callback_path:
                raise HTTPException(status_code=400, detail="Missing callback path.")
            if not callback_path.startswith("/"):
                raise HTTPException(status_code=400, detail="Invalid callback path.")

        if not query:
            raise HTTPException(status_code=400, detail="Missing callback query parameters.")
        callback_result = self._forward_openai_callback_via_container_loopback_fn(
            container_name=session.container_name,
            callback_port=callback_port,
            callback_path=callback_path,
            query=query,
        )
        if not bool(getattr(callback_result, "attempted", False)):
            raise NetworkReachabilityError(
                "Failed to forward OAuth callback to login container. "
                "Reason: container_loopback_not_attempted. "
                "Verify login container name and docker availability."
            )
        if not bool(getattr(callback_result, "ok", False)):
            error_class = str(getattr(callback_result, "error_class", "") or "container_loopback_failed")
            error_detail = str(getattr(callback_result, "error_detail", "") or "").strip()
            message = (
                "Failed to forward OAuth callback to login container. "
                f"Reason: {error_class}. Attempted: http://127.0.0.1:{callback_port}."
            )
            if error_detail:
                message = f"{message} Detail: {error_detail}"
            raise NetworkReachabilityError(message)

        status_code = int(getattr(callback_result, "status_code", 0) or 0)
        response_body = str(getattr(callback_result, "response_body", "") or "")
        target_origin = f"http://127.0.0.1:{callback_port}"

        with self._openai_login_lock:
            current = self._get_openai_login_session()
            if current is not None and current.id == session.id:
                current.log_tail = self._append_tail(
                    current.log_tail,
                    "\n[hub] OAuth callback forwarded to local login server.\n",
                    self._openai_account_login_log_max_chars,
                )
                if current.status in {"running", "waiting_for_browser"}:
                    current.status = "callback_received"
        self._emit_openai_account_session_changed(reason="oauth_callback_forwarded")
        self._logger.info(
            (
                "OpenAI callback forward completed session_id=%s target_origin=%s target_path=%s "
                "status=%s response_summary_present=%s"
            ),
            session.id,
            target_origin,
            callback_path,
            status_code,
            bool(response_body),
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
            "status_code": status_code,
            "target_origin": target_origin,
            "target_path": callback_path,
            "response_summary": self._short_summary(
                self._ansi_escape_re.sub("", response_body),
                max_words=28,
                max_chars=220,
            ),
        }


__all__ = ["OpenAIAccountService"]
