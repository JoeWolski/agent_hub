from __future__ import annotations

# Import HubState runtime globals defined in server.py before mixin import.
import agent_hub.server as _hub_server

globals().update(_hub_server.__dict__)


class HubStateRuntimeMixin:
    def _reconcile_project_build_state(self) -> None:
        state = self.load()
        rebuild_project_ids: list[str] = []
        changed = False

        for project_id, project in state["projects"].items():
            if not isinstance(project, dict):
                continue

            build_status = str(project.get("build_status") or "")
            if build_status in {"pending", "building"}:
                rebuild_project_ids.append(project_id)
                continue
            if build_status != "ready":
                continue

            expected_snapshot_tag = self._project_setup_snapshot_tag(project)
            snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
            snapshot_ready = (
                bool(snapshot_tag)
                and snapshot_tag == expected_snapshot_tag
                and _docker_image_exists(snapshot_tag)
            )
            if snapshot_ready:
                continue

            project["setup_snapshot_image"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""
            project["updated_at"] = _iso_now()
            state["projects"][project_id] = project
            changed = True
            rebuild_project_ids.append(project_id)

        if changed:
            self.save(state, reason="project_build_reconcile")
        for project_id in rebuild_project_ids:
            self._schedule_project_build(project_id)

    def load(self) -> dict[str, Any]:
        state = self._state_store.load(normalizer=self._normalize_loaded_state)
        return state

    def _normalize_loaded_state(self, loaded: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        loaded_copy = copy.deepcopy(loaded)
        projects = loaded_copy.get("projects")
        chats = loaded_copy.get("chats")
        if not isinstance(projects, dict):
            raise ConfigError("Invalid persisted state: 'projects' must be an object.")
        if not isinstance(chats, dict):
            raise ConfigError("Invalid persisted state: 'chats' must be an object.")
        top_level_extras = {
            key: value
            for key, value in loaded_copy.items()
            if key not in {"version", "projects", "chats", "settings"}
        }
        state = {
            **top_level_extras,
            "version": loaded_copy.get("version", 1),
            "projects": projects,
            "chats": chats,
            "settings": self.settings_service.settings_payload(loaded_copy),
        }
        for project_id, project in state["projects"].items():
            if not isinstance(project, dict):
                raise ConfigError(f"Invalid project state for project '{project_id}': entry must be an object.")
        for chat_id, chat in state["chats"].items():
            if not isinstance(chat, dict):
                raise ConfigError(f"Invalid chat state for chat '{chat_id}': entry must be an object.")
            if "codex_args" in chat:
                raise ConfigError(
                    f"Invalid chat state for chat '{chat_id}': codex_args is no longer supported; use agent_args."
                )
            current_args = chat.get("agent_args")
            if isinstance(current_args, list):
                chat["agent_args"] = [str(arg) for arg in current_args]
            else:
                raise ConfigError(f"Invalid chat state for chat '{chat_id}': agent_args must be an array.")
            chat["agent_type"] = _normalize_state_chat_agent_type(chat.get("agent_type"), chat_id=str(chat_id))
            try:
                chat["status"] = _normalize_chat_status(chat.get("status"), strict=True)
            except HTTPException as exc:
                detail = str(exc.detail or "invalid status")
                raise ConfigError(f"Invalid chat state for chat '{chat_id}': {detail}") from exc
            chat["status_reason"] = _compact_whitespace(str(chat.get("status_reason") or ""))
            chat["last_status_transition_at"] = str(
                chat.get("last_status_transition_at") or chat.get("updated_at") or chat.get("created_at") or ""
            )
            chat["start_error"] = _compact_whitespace(str(chat.get("start_error") or ""))
            chat["last_exit_code"] = _normalize_optional_int(chat.get("last_exit_code"))
            chat["last_exit_at"] = str(chat.get("last_exit_at") or "")
            chat["stop_requested_at"] = str(chat.get("stop_requested_at") or "")
            prompts = chat.get("title_user_prompts")
            if isinstance(prompts, list):
                normalized_prompts = [str(item) for item in prompts if str(item).strip()]
                chat["title_user_prompts"] = normalized_prompts
            else:
                chat["title_user_prompts"] = []
            chat["title_cached"] = _truncate_title(str(chat.get("title_cached") or ""), CHAT_TITLE_MAX_CHARS)
            chat["title_prompt_fingerprint"] = str(chat.get("title_prompt_fingerprint") or "")
            chat["title_source"] = str(chat.get("title_source") or "openai")
            chat["title_status"] = str(chat.get("title_status") or "idle")
            chat["title_error"] = str(chat.get("title_error") or "")
            artifacts = _normalize_chat_artifacts(chat.get("artifacts"))
            chat["artifacts"] = artifacts
            current_ids_raw = chat.get("artifact_current_ids")
            if isinstance(current_ids_raw, list):
                chat["artifact_current_ids"] = _normalize_chat_current_artifact_ids(current_ids_raw, artifacts)
            else:
                chat["artifact_current_ids"] = [str(artifact.get("id") or "") for artifact in artifacts if str(artifact.get("id") or "")]
            chat["artifact_prompt_history"] = _normalize_chat_artifact_prompt_history(chat.get("artifact_prompt_history"))
            chat["artifact_publish_token_hash"] = str(chat.get("artifact_publish_token_hash") or "")
            chat["artifact_publish_token_issued_at"] = str(chat.get("artifact_publish_token_issued_at") or "")
            chat["agent_tools_token_hash"] = str(chat.get("agent_tools_token_hash") or "")
            chat["agent_tools_token_issued_at"] = str(chat.get("agent_tools_token_issued_at") or "")
            chat["ready_ack_guid"] = str(chat.get("ready_ack_guid") or "").strip()
            chat["ready_ack_stage"] = _normalize_ready_ack_stage(chat.get("ready_ack_stage"))
            chat["ready_ack_at"] = str(chat.get("ready_ack_at") or "")
            ready_ack_meta = chat.get("ready_ack_meta")
            chat["ready_ack_meta"] = ready_ack_meta if isinstance(ready_ack_meta, dict) else {}
            chat["create_request_id"] = _compact_whitespace(str(chat.get("create_request_id") or "")).strip()
        return state, state != loaded

    @staticmethod
    def _event_queue_put(listener: queue.Queue[dict[str, Any] | None], value: dict[str, Any] | None) -> None:
        try:
            listener.put_nowait(value)
            return
        except queue.Full:
            pass

        try:
            listener.get_nowait()
        except queue.Empty:
            return

        try:
            listener.put_nowait(value)
        except queue.Full:
            return

    def _emit_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {"type": str(event_type), "payload": payload or {}, "sent_at": _iso_now()}
        with self._events_lock:
            listeners = list(self._event_listeners)
        LOGGER.debug("Emitting hub event type=%s listeners=%d", event_type, len(listeners))
        for listener in listeners:
            self._event_queue_put(listener, event)

    def _emit_state_changed(self, reason: str = "") -> None:
        self._emit_event(EVENT_TYPE_STATE_CHANGED, {"reason": str(reason or "")})

    def _emit_auth_changed(self, reason: str = "") -> None:
        self._emit_event(EVENT_TYPE_AUTH_CHANGED, {"reason": str(reason or "")})

    def _emit_project_build_log(self, project_id: str, text: str, replace: bool = False) -> None:
        self._emit_event(
            EVENT_TYPE_PROJECT_BUILD_LOG,
            {
                "project_id": str(project_id),
                "text": str(text or ""),
                "replace": bool(replace),
            },
        )

    def _emit_auto_config_log(self, request_id: str, text: str, replace: bool = False) -> None:
        self._emit_event(
            EVENT_TYPE_AUTO_CONFIG_LOG,
            {
                "request_id": str(request_id),
                "text": str(text or ""),
                "replace": bool(replace),
            },
        )

    def _normalize_auto_config_request_id(self, request_id: Any) -> str:
        return str(request_id or "").strip()[:AUTO_CONFIG_REQUEST_ID_MAX_CHARS]

    @staticmethod
    def _normalize_project_build_request_id(project_id: Any) -> str:
        return str(project_id or "").strip()

    def _auto_config_request_state(self, request_id: str) -> AutoConfigRequestState | None:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        if not normalized_request_id:
            return None
        with self._auto_config_requests_lock:
            return self._auto_config_requests.get(normalized_request_id)

    def _register_auto_config_request(self, request_id: str) -> None:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        if not normalized_request_id:
            return
        with self._auto_config_requests_lock:
            # Keep existing request state so cancellation/process tracking cannot be reset
            # by repeated registration calls for the same request id.
            if normalized_request_id in self._auto_config_requests:
                return
            self._auto_config_requests[normalized_request_id] = AutoConfigRequestState(request_id=normalized_request_id)

    def _set_auto_config_request_process(self, request_id: str, process: subprocess.Popen[str] | None = None) -> None:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        if not normalized_request_id:
            return
        should_stop_process = False
        with self._auto_config_requests_lock:
            state = self._auto_config_requests.get(normalized_request_id)
            if state is None:
                return
            state.process = process
            should_stop_process = (
                bool(state.cancel_requested)
                and process is not None
                and _is_process_running(process.pid)
            )
        if should_stop_process:
            _stop_process(process.pid)

    def _is_auto_config_request_cancelled(self, request_id: str) -> bool:
        state = self._auto_config_request_state(request_id)
        return bool(state and state.cancel_requested)

    def _clear_auto_config_request(self, request_id: str) -> None:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        if not normalized_request_id:
            return
        with self._auto_config_requests_lock:
            self._auto_config_requests.pop(normalized_request_id, None)

    def _project_build_request_state(self, project_id: str) -> ProjectBuildRequestState | None:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            return None
        with self._project_build_requests_lock:
            return self._project_build_requests.get(normalized_project_id)

    def _register_project_build_request(self, project_id: str) -> None:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            return
        with self._project_build_requests_lock:
            existing = self._project_build_requests.get(normalized_project_id)
            if existing is None:
                self._project_build_requests[normalized_project_id] = ProjectBuildRequestState(project_id=normalized_project_id)
                return
            existing.cancel_requested = False

    def _set_project_build_request_process(
        self,
        project_id: str,
        process: subprocess.Popen[str] | None = None,
    ) -> None:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            return
        should_stop_process = False
        with self._project_build_requests_lock:
            state = self._project_build_requests.get(normalized_project_id)
            if state is None:
                state = ProjectBuildRequestState(project_id=normalized_project_id)
                self._project_build_requests[normalized_project_id] = state
            state.process = process
            should_stop_process = (
                bool(state.cancel_requested)
                and process is not None
                and _is_process_running(process.pid)
            )
        if should_stop_process:
            _stop_process(process.pid)

    def _is_project_build_cancelled(self, project_id: str) -> bool:
        state = self._project_build_request_state(project_id)
        return bool(state and state.cancel_requested)

    def _clear_project_build_request(self, project_id: str) -> None:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            return
        with self._project_build_requests_lock:
            self._project_build_requests.pop(normalized_project_id, None)

    def _mark_project_build_cancelled(self, project_id: str, message: str = PROJECT_BUILD_CANCELLED_ERROR) -> bool:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            return False
        state = self.load()
        project = state["projects"].get(normalized_project_id)
        if project is None:
            return False
        if str(project.get("build_status") or "") not in {"pending", "building"}:
            return False
        now = _iso_now()
        project["build_status"] = "cancelled"
        project["build_error"] = str(message or PROJECT_BUILD_CANCELLED_ERROR)
        project["build_finished_at"] = now
        project["updated_at"] = now
        state["projects"][normalized_project_id] = project
        self.save(state, reason="project_build_cancelled")
        return True

    def cancel_auto_configure_project(self, request_id: str) -> dict[str, Any]:
        normalized_request_id = self._normalize_auto_config_request_id(request_id)
        if not normalized_request_id:
            raise HTTPException(status_code=400, detail="request_id is required.")

        process_to_cancel: subprocess.Popen[str] | None = None
        with self._auto_config_requests_lock:
            request_state = self._auto_config_requests.get(normalized_request_id)
            if request_state is None:
                return {"request_id": normalized_request_id, "cancelled": False, "active": False}
            request_state.cancel_requested = True
            process_to_cancel = request_state.process if request_state.process is not None else None

        was_active = bool(process_to_cancel is not None and _is_process_running(process_to_cancel.pid))
        if was_active:
            _stop_process(process_to_cancel.pid)
        return {"request_id": normalized_request_id, "cancelled": True, "active": was_active}

    def cancel_project_build(self, project_id: Any) -> dict[str, Any]:
        normalized_project_id = self._normalize_project_build_request_id(project_id)
        if not normalized_project_id:
            raise HTTPException(status_code=400, detail="project_id is required.")
        project = self.project(normalized_project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        if str(project.get("build_status") or "") not in {"pending", "building"}:
            return {"project_id": normalized_project_id, "cancelled": False, "active": False}

        process_to_cancel: subprocess.Popen[str] | None = None
        with self._project_build_requests_lock:
            request_state = self._project_build_requests.get(normalized_project_id)
            if request_state is None:
                request_state = ProjectBuildRequestState(project_id=normalized_project_id)
                self._project_build_requests[normalized_project_id] = request_state
            request_state.cancel_requested = True
            process_to_cancel = request_state.process if request_state.process is not None else None

        was_active = bool(process_to_cancel is not None and _is_process_running(process_to_cancel.pid))
        if was_active:
            _stop_process(process_to_cancel.pid)
        cancelled = self._mark_project_build_cancelled(normalized_project_id)
        if not cancelled:
            self._clear_project_build_request(normalized_project_id)
        return {"project_id": normalized_project_id, "cancelled": cancelled, "active": was_active}

    def _emit_openai_account_session_changed(self, reason: str = "") -> None:
        payload = self.openai_account_session_payload()
        payload["reason"] = str(reason or "")
        self._emit_event(EVENT_TYPE_OPENAI_ACCOUNT_SESSION, payload)

    def _emit_agent_capabilities_changed(self, reason: str = "") -> None:
        self._emit_event(EVENT_TYPE_AGENT_CAPABILITIES_CHANGED, {"reason": str(reason or "")})

    def _agent_capabilities_payload_locked(self) -> dict[str, Any]:
        return _normalize_agent_capabilities_payload(self._agent_capabilities)

    def _write_agent_capabilities_cache_locked(self) -> None:
        normalized = self._agent_capabilities_payload_locked()
        with self.agent_capabilities_cache_file.open("w", encoding="utf-8") as fp:
            json.dump(normalized, fp, indent=2)
        self._agent_capabilities = normalized

    def _load_agent_capabilities_cache(self) -> None:
        with self._agent_capabilities_lock:
            if not self.agent_capabilities_cache_file.exists():
                self._agent_capabilities = _default_agent_capabilities_cache_payload()
                return
            try:
                raw_payload = json.loads(self.agent_capabilities_cache_file.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, json.JSONDecodeError):
                self._agent_capabilities = _default_agent_capabilities_cache_payload()
                return
            normalized = _normalize_agent_capabilities_payload(raw_payload)
            normalized["discovery_in_progress"] = False
            self._agent_capabilities = normalized
            try:
                self._write_agent_capabilities_cache_locked()
            except OSError:
                return

    def agent_capabilities_payload(self) -> dict[str, Any]:
        with self._agent_capabilities_lock:
            return self._agent_capabilities_payload_locked()

    def _discover_agent_capabilities_for_type(self, agent_type: str, previous: dict[str, Any]) -> dict[str, Any]:
        resolved_type = _normalize_chat_agent_type(agent_type, strict=True)
        commands = AGENT_CAPABILITY_DISCOVERY_COMMANDS_BY_TYPE.get(resolved_type, ())
        probe_run_args = _agent_capability_probe_docker_run_args(
            local_uid=self.local_uid,
            local_gid=self.local_gid,
            local_supp_gids_csv=self.local_supp_gids,
            local_umask=self.local_umask,
            local_user=self.local_user,
            host_codex_dir=self.host_codex_dir,
            config_file=self.config_file,
        )
        discovered_models: list[str] = ["default"]
        discovered_reasoning_modes: list[str] = ["default"]
        last_error = ""
        now = _iso_now()

        for raw_cmd in commands:
            cmd = [str(token) for token in raw_cmd]
            return_code, output_text = _run_agent_capability_probe(
                cmd,
                AGENT_CAPABILITY_DISCOVERY_TIMEOUT_SECONDS,
                docker_run_args=probe_run_args,
            )
            if return_code == 127:
                last_error = f"command not found: {cmd[0]}"
                LOGGER.info("Agent capability discovery skipped for agent=%s: %s", resolved_type, last_error)
                continue
            if return_code == 124:
                last_error = f"timeout running command: {' '.join(cmd)}"
                LOGGER.warning("Agent capability discovery timeout agent=%s cmd=%s", resolved_type, cmd)
                continue
            elif return_code != 0:
                last_error = f"command failed ({return_code}): {' '.join(cmd)}"
                LOGGER.info(
                    "Agent capability discovery command failed agent=%s cmd=%s return_code=%d output=%s",
                    resolved_type,
                    cmd,
                    return_code,
                    _short_summary(output_text, max_words=60, max_chars=600),
                )
                continue

            parsed_models = _extract_model_candidates_from_output(output_text, resolved_type)
            if parsed_models:
                discovered_models = _normalize_model_options_for_agent(
                    resolved_type,
                    parsed_models,
                    ["default"],
                )
            parsed_reasoning = _extract_reasoning_candidates_from_output(output_text, resolved_type)
            if parsed_reasoning:
                discovered_reasoning_modes = _normalize_reasoning_mode_options_for_agent(
                    resolved_type,
                    parsed_reasoning,
                    ["default"],
                )

            if (
                _option_count_excluding_default(discovered_models) >= 1
                and _option_count_excluding_default(discovered_reasoning_modes) >= 1
            ):
                break

        if not discovered_models:
            discovered_models = ["default"]
        if not discovered_reasoning_modes:
            discovered_reasoning_modes = _normalize_reasoning_mode_options_for_agent(
                resolved_type,
                [],
                ["default"],
            )

        return {
            "agent_type": resolved_type,
            "label": str(previous.get("label") or AGENT_LABEL_BY_TYPE.get(resolved_type, resolved_type.title())),
            "models": discovered_models,
            "reasoning_modes": discovered_reasoning_modes,
            "updated_at": now,
            "last_error": last_error,
        }

    def _agent_capability_discovery_worker(self) -> None:
        try:
            with self._agent_capabilities_lock:
                baseline_payload = self._agent_capabilities_payload_locked()
            baseline_agents = {
                str(agent.get("agent_type") or ""): dict(agent)
                for agent in baseline_payload.get("agents") or []
                if isinstance(agent, dict)
            }

            discovered_agents: list[dict[str, Any]] = []
            for agent_type in _ordered_supported_agent_types():
                previous = baseline_agents.get(agent_type) or _agent_capability_defaults_for_type(agent_type)
                discovered_agents.append(self._discover_agent_capabilities_for_type(agent_type, previous))

            finished_at = _iso_now()
            with self._agent_capabilities_lock:
                merged_payload = self._agent_capabilities_payload_locked()
                merged_payload["updated_at"] = finished_at
                merged_payload["discovery_in_progress"] = False
                merged_payload["discovery_finished_at"] = finished_at
                merged_payload["agents"] = discovered_agents
                self._agent_capabilities = _normalize_agent_capabilities_payload(merged_payload)
                self._write_agent_capabilities_cache_locked()
        finally:
            with self._agent_capabilities_lock:
                active = self._agent_capabilities_discovery_thread
                if active is not None and active.ident == current_thread().ident:
                    self._agent_capabilities_discovery_thread = None
                self._agent_capabilities["discovery_in_progress"] = False
                if not str(self._agent_capabilities.get("discovery_finished_at") or "").strip():
                    self._agent_capabilities["discovery_finished_at"] = _iso_now()
                self._agent_capabilities = _normalize_agent_capabilities_payload(self._agent_capabilities)
                try:
                    self._write_agent_capabilities_cache_locked()
                except OSError:
                    pass
            self._emit_agent_capabilities_changed(reason="discovery_finished")

    def start_agent_capabilities_discovery(self) -> dict[str, Any]:
        payload_to_return: dict[str, Any]
        should_emit = False
        with self._agent_capabilities_lock:
            existing = self._agent_capabilities_discovery_thread
            if existing is not None and existing.is_alive():
                return self._agent_capabilities_payload_locked()

            started_at = _iso_now()
            self._agent_capabilities["discovery_in_progress"] = True
            self._agent_capabilities["discovery_started_at"] = started_at
            self._agent_capabilities["discovery_finished_at"] = ""
            self._agent_capabilities = _normalize_agent_capabilities_payload(self._agent_capabilities)
            self._write_agent_capabilities_cache_locked()

            worker = Thread(target=self._agent_capability_discovery_worker, daemon=True)
            self._agent_capabilities_discovery_thread = worker
            worker.start()
            payload_to_return = self._agent_capabilities_payload_locked()
            should_emit = True
        if should_emit:
            self._emit_agent_capabilities_changed(reason="discovery_started")
        return payload_to_return

    def attach_events(self) -> queue.Queue[dict[str, Any] | None]:
        listener: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=HUB_EVENT_QUEUE_MAX)
        with self._events_lock:
            self._event_listeners.add(listener)
        return listener

    def detach_events(self, listener: queue.Queue[dict[str, Any] | None]) -> None:
        with self._events_lock:
            self._event_listeners.discard(listener)

    def events_snapshot(self) -> dict[str, Any]:
        state_payload = self.state_payload()
        build_logs: dict[str, str] = {}
        for project in state_payload.get("projects") or []:
            project_id = str(project.get("id") or "")
            if not project_id:
                continue
            if str(project.get("build_status") or "") != "building":
                continue
            log_path = self.project_build_log(project_id)
            if not log_path.exists():
                build_logs[project_id] = ""
                continue
            build_logs[project_id] = log_path.read_text(encoding="utf-8", errors="ignore")
        return {
            "state": state_payload,
            "auth": self.auth_settings_payload(),
            "openai_account_session": self.openai_account_session_payload(),
            "agent_capabilities": self.agent_capabilities_payload(),
            "project_build_logs": build_logs,
        }

    def save(self, state: dict[str, Any], reason: str = "") -> None:
        self._state_store.save_raw(state)
        self._emit_state_changed(reason=reason)

    def _transition_chat_status(
        self,
        chat_id: str,
        chat: dict[str, Any],
        next_status: str,
        reason: str,
    ) -> bool:
        previous_status = _normalize_chat_status(chat.get("status"))
        resolved_next_status = _normalize_chat_status(next_status)
        transition_reason = _compact_whitespace(str(reason or "")).strip() or "unspecified"
        changed = previous_status != resolved_next_status
        transitioned_at = _iso_now()
        chat["status"] = resolved_next_status
        chat["status_reason"] = transition_reason
        chat["last_status_transition_at"] = transitioned_at
        chat["updated_at"] = transitioned_at
        if changed:
            LOGGER.info(
                "Chat state transition chat_id=%s from=%s to=%s reason=%s",
                chat_id,
                previous_status,
                resolved_next_status,
                transition_reason,
            )
        return changed

    @staticmethod
    def _chat_start_error_detail(exc: Exception) -> str:
        detail: Any = ""
        if isinstance(exc, HTTPException):
            detail = exc.detail
        elif isinstance(exc, click.ClickException):
            detail = exc.message
        else:
            detail = str(exc)
        if isinstance(detail, (dict, list)):
            try:
                detail = json.dumps(detail, sort_keys=True)
            except (TypeError, ValueError):
                detail = str(detail)
        message = _compact_whitespace(str(detail or "")).strip()
        if message:
            return message
        return exc.__class__.__name__

    def _mark_chat_start_failed(self, chat_id: str, *, detail: str, reason: str) -> dict[str, Any] | None:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            return None
        self._transition_chat_status(chat_id, chat, CHAT_STATUS_FAILED, reason)
        chat["pid"] = None
        chat["start_error"] = _compact_whitespace(str(detail or "")).strip()
        chat["artifact_publish_token_hash"] = ""
        chat["artifact_publish_token_issued_at"] = ""
        chat["agent_tools_token_hash"] = ""
        chat["agent_tools_token_issued_at"] = ""
        chat["last_exit_code"] = None
        chat["last_exit_at"] = _iso_now()
        chat["stop_requested_at"] = ""
        state["chats"][chat_id] = chat
        self.save(state, reason=reason)
        return dict(chat)

    def _record_chat_runtime_exit(self, chat_id: str, exit_code: int | None, *, reason: str) -> None:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            LOGGER.info(
                "Chat runtime exit ignored because chat is missing chat_id=%s reason=%s exit_code=%s",
                chat_id,
                reason,
                exit_code,
            )
            return
        normalized_reason = _compact_whitespace(str(reason or "")).strip() or "chat_runtime_exited"
        normalized_status = _normalize_chat_status(chat.get("status"))
        stop_requested = bool(str(chat.get("stop_requested_at") or "").strip())
        if stop_requested:
            requested_reason = _compact_whitespace(str(chat.get("status_reason") or "")).strip()
            if requested_reason in {CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED, CHAT_STATUS_REASON_USER_CLOSED_TAB}:
                stop_reason = requested_reason
            else:
                stop_reason = f"{normalized_reason}:stop_requested"
            self._transition_chat_status(chat_id, chat, CHAT_STATUS_STOPPED, stop_reason)
            chat["start_error"] = ""
            chat["stop_requested_at"] = ""
        elif normalized_status in {CHAT_STATUS_RUNNING, CHAT_STATUS_STARTING}:
            self._transition_chat_status(chat_id, chat, CHAT_STATUS_FAILED, f"{normalized_reason}:unexpected_exit")
            if not str(chat.get("start_error") or "").strip():
                chat["start_error"] = "Chat process exited unexpectedly."
        else:
            LOGGER.info(
                "Chat runtime exit observed without status transition chat_id=%s status=%s reason=%s exit_code=%s",
                chat_id,
                normalized_status,
                normalized_reason,
                exit_code,
            )
            chat["status"] = normalized_status
            if not str(chat.get("status_reason") or "").strip():
                chat["status_reason"] = normalized_reason
        chat["pid"] = None
        chat["artifact_publish_token_hash"] = ""
        chat["artifact_publish_token_issued_at"] = ""
        chat["agent_tools_token_hash"] = ""
        chat["agent_tools_token_issued_at"] = ""
        chat["last_exit_code"] = _normalize_optional_int(exit_code)
        chat["last_exit_at"] = _iso_now()
        chat["updated_at"] = _iso_now()
        state["chats"][chat_id] = chat
        self.save(state, reason=normalized_reason)

    def settings_payload(self) -> dict[str, Any]:
        state = self.load()
        return self.settings_service.settings_payload(state)

    def runtime_flags_payload(self) -> dict[str, Any]:
        return {
            "ui_lifecycle_debug": bool(self.ui_lifecycle_debug),
        }

    def default_chat_agent_type(self) -> str:
        settings = self.settings_payload()
        return str(settings.get("default_agent_type") or DEFAULT_CHAT_AGENT_TYPE)

    def update_settings(self, update: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        settings = self.settings_service.update_settings(state, update)
        state["settings"] = settings
        self.save(state, reason="settings_updated")
        return settings

    def _git_identity_env_vars_from_settings(self) -> list[str]:
        settings = self.settings_payload()
        git_user_name = str(settings.get("git_user_name") or "").strip()
        git_user_email = str(settings.get("git_user_email") or "").strip()
        if not git_user_name or not git_user_email:
            return []
        return [
            f"AGENT_HUB_GIT_USER_NAME={git_user_name}",
            f"AGENT_HUB_GIT_USER_EMAIL={git_user_email}",
        ]

    def _openai_credentials_arg(self) -> list[str]:
        return ["--credentials-file", str(self.openai_credentials_file)]

    def chat_workdir(self, chat_id: str) -> Path:
        chat = self.chat(chat_id)
        if chat is not None and chat.get("workspace"):
            return Path(str(chat["workspace"]))
        return self.chat_dir / chat_id

    def project_workdir(self, project_id: str) -> Path:
        return self.project_dir / project_id

    def project_tmp_workdir(self, project_id: str) -> Path:
        return self.runtime_project_tmp_dir / str(project_id or "") / RUNTIME_TMP_WORKSPACE_DIR_NAME

    def chat_tmp_workdir(self, project_id: str, chat_id: str) -> Path:
        return (
            self.runtime_project_tmp_dir
            / str(project_id or "")
            / RUNTIME_TMP_CHATS_DIR_NAME
            / str(chat_id or "")
        )

    def chat_log(self, chat_id: str) -> Path:
        return self.log_dir / f"{chat_id}.log"

    def project_build_log(self, project_id: str) -> Path:
        return self.log_dir / f"project-{project_id}.log"

    def _chat_runtime_config_path(self, chat_id: str) -> Path:
        return self.chat_runtime_configs_dir / f"{chat_id}.toml"

    @staticmethod
    def _strip_mcp_server_table(config_text: str, server_name: str) -> str:
        if not config_text:
            return ""
        escaped_name = re.escape(server_name)
        pattern = re.compile(r"(?ms)^\[mcp_servers\." + escaped_name + r"(?:\.[^\]]+)?\]\n.*?(?=^\[|\Z)")
        stripped = re.sub(pattern, "", config_text)
        return stripped.rstrip() + "\n"

    def _prepare_chat_runtime_config(
        self,
        chat_id: str,
        agent_type: str,
        *,
        agent_tools_url: str,
        agent_tools_token: str,
        agent_tools_project_id: str,
        agent_tools_chat_id: str,
        trusted_project_path: str = "",
    ) -> Path:
        from agent_cli import providers as agent_providers
        try:
            base_text = self.config_file.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise ConfigError(f"Failed to read config file: {self.config_file}") from exc

        normalized_agent_tools_url = str(agent_tools_url or "").strip()
        normalized_agent_tools_token = str(agent_tools_token or "").strip()
        if not normalized_agent_tools_url:
            raise ConfigError(f"Missing required {AGENT_TOOLS_URL_ENV} while preparing runtime config for {chat_id}.")
        if not normalized_agent_tools_token:
            raise ConfigError(
                f"Missing required {AGENT_TOOLS_TOKEN_ENV} while preparing runtime config for {chat_id}."
            )

        self._ensure_agent_tools_mcp_runtime_script()

        agent_provider = agent_providers.get_provider(agent_type)
        if isinstance(agent_provider, agent_providers.CodexProvider):
            base_text = _upsert_codex_trusted_project_config(base_text, trusted_project_path)
        mcp_env = {
            AGENT_TOOLS_URL_ENV: normalized_agent_tools_url,
            AGENT_TOOLS_TOKEN_ENV: normalized_agent_tools_token,
            AGENT_TOOLS_PROJECT_ID_ENV: str(agent_tools_project_id or '').strip(),
            AGENT_TOOLS_CHAT_ID_ENV: str(agent_tools_chat_id or '').strip(),
        }
        merged_text = agent_provider.build_mcp_config(
            base_config_text=base_text,
            mcp_env=mcp_env,
            script_path=AGENT_TOOLS_MCP_CONTAINER_SCRIPT_PATH,
        )

        ext = ".json" if isinstance(
            agent_provider,
            (agent_providers.ClaudeProvider, agent_providers.GeminiProvider),
        ) else ".toml"
        runtime_config_path = self.chat_runtime_configs_dir / f"{chat_id}{ext}"
        _write_private_env_file(runtime_config_path, merged_text)
        return runtime_config_path

    def _ensure_agent_tools_mcp_runtime_script(self) -> None:
        source_path = _agent_tools_mcp_source_path()
        try:
            script_text = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Failed to read agent_tools MCP source script: {source_path}") from exc

        if self.agent_tools_mcp_runtime_script.exists():
            try:
                existing_text = self.agent_tools_mcp_runtime_script.read_text(encoding="utf-8")
            except OSError:
                existing_text = ""
            if existing_text == script_text:
                return

        try:
            _write_private_env_file(self.agent_tools_mcp_runtime_script, script_text)
        except OSError as exc:
            raise ConfigError(
                f"Failed to materialize agent_tools MCP runtime script: {self.agent_tools_mcp_runtime_script}"
            ) from exc

    def _chat_agent_tools_url(self, chat_id: str) -> str:
        return f"{self.artifact_publish_base_url}/api/chats/{chat_id}/agent-tools"

    def _chat_artifact_publish_url(self, chat_id: str) -> str:
        return f"{self.artifact_publish_base_url}/api/chats/{chat_id}/artifacts/publish"

    @staticmethod
    def _chat_artifact_download_url(chat_id: str, artifact_id: str) -> str:
        return f"/api/chats/{chat_id}/artifacts/{artifact_id}/download"

    @staticmethod
    def _chat_artifact_preview_url(chat_id: str, artifact_id: str) -> str:
        return f"/api/chats/{chat_id}/artifacts/{artifact_id}/preview"

    def _chat_artifact_public_payload(self, chat_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(artifact.get("id") or "")
        return {
            "id": artifact_id,
            "name": _normalize_artifact_name(artifact.get("name"), fallback=Path(str(artifact.get("relative_path") or "")).name),
            "relative_path": str(artifact.get("relative_path") or ""),
            "size_bytes": int(artifact.get("size_bytes") or 0),
            "created_at": str(artifact.get("created_at") or ""),
            "preview_url": self._chat_artifact_preview_url(chat_id, artifact_id),
            "download_url": self._chat_artifact_download_url(chat_id, artifact_id),
        }

    def _chat_artifact_history_public_payload(self, chat_id: str, history_entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "prompt": _sanitize_submitted_prompt(history_entry.get("prompt"))[:CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS],
            "archived_at": str(history_entry.get("archived_at") or ""),
            "artifacts": [
                self._chat_artifact_public_payload(chat_id, artifact)
                for artifact in _normalize_chat_artifacts(history_entry.get("artifacts"))
            ],
        }

    def _resolve_chat_artifact_file(self, chat_id: str, submitted_path: Any) -> tuple[Path, str]:
        raw_path = str(submitted_path or "").strip()
        if not raw_path:
            raise HTTPException(status_code=400, detail="path is required.")
        if len(raw_path) > CHAT_ARTIFACT_PATH_MAX_CHARS * 2:
            raise HTTPException(status_code=400, detail="path is too long.")

        workspace = self.chat_workdir(chat_id).resolve()
        candidate = Path(raw_path).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()
        if not resolved.exists():
            LOGGER.warning(
                "Artifact file not found for chat_id=%s raw_path=%s resolved=%s",
                chat_id,
                raw_path,
                resolved,
            )
            raise HTTPException(status_code=404, detail=f"Artifact file not found: {raw_path}")
        if not resolved.is_file():
            LOGGER.warning(
                "Artifact path is not a file for chat_id=%s raw_path=%s resolved=%s",
                chat_id,
                raw_path,
                resolved,
            )
            raise HTTPException(status_code=400, detail=f"Artifact path is not a file: {raw_path}")
        try:
            relative_path_value = resolved.relative_to(workspace).as_posix()
        except ValueError:
            # Preserve deterministic, non-empty metadata for files outside workspace.
            relative_path_value = f"external/{resolved.as_posix()}"
        relative_path = _coerce_artifact_relative_path(relative_path_value)
        if not relative_path:
            LOGGER.warning("Artifact path normalized to empty for chat_id=%s raw_path=%s resolved=%s", chat_id, raw_path, resolved)
            raise HTTPException(status_code=400, detail="Artifact path is invalid.")
        return resolved, relative_path

    @staticmethod
    def _require_artifact_publish_token(chat: dict[str, Any], token: Any) -> None:
        expected_hash = str(chat.get("artifact_publish_token_hash") or "")
        if not expected_hash:
            raise HTTPException(status_code=409, detail="Artifact publishing is unavailable until the chat is started.")

        submitted_token = str(token or "").strip()
        if not submitted_token:
            raise HTTPException(status_code=401, detail="Missing artifact publish token.")
        submitted_hash = _hash_artifact_publish_token(submitted_token)
        if not submitted_hash or not hmac.compare_digest(submitted_hash, expected_hash):
            raise HTTPException(status_code=403, detail="Invalid artifact publish token.")

    @staticmethod
    def _require_session_artifact_publish_token(session: dict[str, Any], token: Any) -> None:
        expected_hash = str(session.get("artifact_publish_token_hash") or "")
        if not expected_hash:
            raise HTTPException(status_code=409, detail="Artifact publishing is unavailable for this session.")

        submitted_token = str(token or "").strip()
        if not submitted_token:
            raise HTTPException(status_code=401, detail="Missing artifact publish token.")
        submitted_hash = _hash_artifact_publish_token(submitted_token)
        if not submitted_hash or not hmac.compare_digest(submitted_hash, expected_hash):
            raise HTTPException(status_code=403, detail="Invalid artifact publish token.")

    @staticmethod
    def _require_agent_tools_token(chat: dict[str, Any], token: Any) -> None:
        expected_hash = str(chat.get("agent_tools_token_hash") or "")
        if not expected_hash:
            raise HTTPException(status_code=409, detail="agent_tools is unavailable until the chat is started.")

        submitted_token = str(token or "").strip()
        if not submitted_token:
            raise HTTPException(status_code=401, detail="Missing agent_tools token.")
        submitted_hash = _hash_agent_tools_token(submitted_token)
        if not submitted_hash or not hmac.compare_digest(submitted_hash, expected_hash):
            raise HTTPException(status_code=403, detail="Invalid agent_tools token.")

    @staticmethod
    def _validated_ready_ack_guid(*, expected: str, submitted: Any) -> str:
        normalized_expected = str(expected or "").strip()
        if not normalized_expected:
            raise HTTPException(status_code=409, detail="Ready acknowledgement is unavailable for this runtime.")
        normalized_submitted = str(submitted or "").strip()
        if not normalized_submitted:
            raise HTTPException(status_code=400, detail="guid is required.")
        if normalized_submitted != normalized_expected:
            raise HTTPException(status_code=400, detail="guid does not match the expected runtime readiness token.")
        return normalized_submitted

    def acknowledge_agent_tools_chat_ready(
        self,
        chat_id: str,
        *,
        token: Any,
        guid: Any,
        stage: Any = AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
        meta: Any = None,
    ) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._require_agent_tools_token(chat, token)
        resolved_guid = self._validated_ready_ack_guid(expected=chat.get("ready_ack_guid"), submitted=guid)
        resolved_stage = _normalize_ready_ack_stage(stage)
        resolved_meta = meta if isinstance(meta, dict) else {}
        acknowledged_at = _iso_now()
        chat["ready_ack_guid"] = resolved_guid
        chat["ready_ack_stage"] = resolved_stage
        chat["ready_ack_at"] = acknowledged_at
        chat["ready_ack_meta"] = resolved_meta
        chat["updated_at"] = acknowledged_at
        state["chats"][chat_id] = chat
        self.save(state, reason="agent_tools_chat_ready_ack")
        return {
            "chat_id": chat_id,
            "guid": resolved_guid,
            "stage": resolved_stage,
            "acknowledged_at": acknowledged_at,
            "meta": resolved_meta,
        }

    def _chat_and_project_for_agent_tools(self, chat_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project_id = str(chat.get("project_id") or "").strip()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return chat, project

    @staticmethod
    def _credential_lookup_key(credential: dict[str, Any]) -> str:
        return str(credential.get("credential_id") or "").strip()

    def _credential_from_id(self, credential_id: str) -> dict[str, Any] | None:
        normalized_id = str(credential_id or "").strip()
        if not normalized_id:
            return None
        for credential in self._credential_catalog():
            if self._credential_lookup_key(credential) == normalized_id:
                return credential
        return None

    def _materialize_agent_tool_credential(
        self,
        credential: dict[str, Any],
        *,
        context_key: str,
    ) -> dict[str, Any]:
        credential_id = str(credential.get("credential_id") or "").strip()
        kind = str(credential.get("kind") or "").strip()
        provider = str(credential.get("provider") or "").strip()
        host = str(credential.get("host") or "").strip()
        scheme = _normalize_github_credential_scheme(credential.get("scheme"), field_name="scheme")
        account_login = str(credential.get("account_login") or "").strip()
        account_name = str(credential.get("account_name") or "").strip()
        account_email = str(credential.get("account_email") or "").strip()

        username = account_login
        secret = ""
        if kind == "github_app_installation":
            installation_id = int(str(credential_id).split(":", 1)[1]) if ":" in credential_id else 0
            if installation_id <= 0:
                raise CredentialResolutionError(f"Invalid GitHub App credential id: {credential_id}")
            installation_status = self.github_app_auth_status()
            if int(installation_status.get("installation_id") or 0) != installation_id:
                raise CredentialResolutionError("GitHub App installation credential is no longer connected.")
            token, _expires_at = self._github_installation_token(installation_id)
            username = "x-access-token"
            secret = token
        elif kind == "personal_access_token":
            matching = None
            for token in self._connected_personal_access_tokens(provider):
                if str(token.get("token_id") or "").strip() == credential_id:
                    matching = token
                    break
            if matching is None:
                raise CredentialResolutionError("Personal access token credential is no longer connected.")
            username = str(matching.get("account_login") or "").strip()
            secret = str(matching.get("personal_access_token") or "").strip()
            account_login = str(matching.get("account_login") or "").strip()
            account_name = str(matching.get("account_name") or "").strip()
            account_email = str(matching.get("account_email") or "").strip()
            host = str(matching.get("host") or "").strip()
            scheme = _normalize_github_credential_scheme(matching.get("scheme"), field_name="scheme")
        else:
            raise CredentialResolutionError(f"Unsupported credential kind: {kind}")

        if not username or not secret or not host:
            raise CredentialResolutionError("Resolved credential is missing required fields.")

        credential_file = self._write_github_git_credentials(
            host=host,
            username=username,
            secret=secret,
            scheme=scheme,
            credential_id=credential_id,
            context_key=context_key,
        )
        encoded_username = urllib.parse.quote(username, safe="")
        encoded_secret = urllib.parse.quote(secret, safe="")
        credential_line = f"{scheme}://{encoded_username}:{encoded_secret}@{host}"
        git_identity_env: dict[str, str] = {}
        if kind == "personal_access_token":
            git_user_name = account_name or account_login
            if git_user_name and account_email:
                git_identity_env = {
                    "AGENT_HUB_GIT_USER_NAME": git_user_name,
                    "AGENT_HUB_GIT_USER_EMAIL": account_email,
                }
        return {
            "credential_id": credential_id,
            "kind": kind,
            "provider": provider,
            "host": host,
            "scheme": scheme,
            "account_login": account_login,
            "account_name": account_name,
            "account_email": account_email,
            "summary": str(credential.get("summary") or ""),
            "username": username,
            "secret": secret,
            "credential_line": credential_line,
            "host_credential_file": credential_file,
            "git_env": self._git_env_for_credentials_file(credential_file, host, scheme=scheme),
            "git_identity_env": git_identity_env,
        }

    def _resolve_agent_tools_credential_ids(
        self,
        project: dict[str, Any],
        mode: str,
        credential_ids: list[str],
    ) -> list[str]:
        available = self._project_available_credentials(project)
        available_ids = [self._credential_lookup_key(entry) for entry in available if self._credential_lookup_key(entry)]
        available_id_set = set(available_ids)
        requested_ids = [str(item or "").strip() for item in credential_ids if str(item or "").strip()]

        if mode == PROJECT_CREDENTIAL_BINDING_MODE_ALL:
            return available_ids
        if mode in {PROJECT_CREDENTIAL_BINDING_MODE_SET, PROJECT_CREDENTIAL_BINDING_MODE_SINGLE}:
            selected = requested_ids
            if not selected:
                selected = self._resolved_project_credential_ids(project)
            selected = [credential_id for credential_id in selected if credential_id in available_id_set]
            if mode == PROJECT_CREDENTIAL_BINDING_MODE_SINGLE and selected:
                return selected[:1]
            return selected

        if mode == PROJECT_CREDENTIAL_BINDING_MODE_AUTO:
            contexts = self._github_repo_all_auth_contexts(str(project.get("repo_url") or ""), project=project)
            resolved_ids: list[str] = []
            for _m, _h, auth_payload in contexts:
                candidate_id = str(auth_payload.get("credential_id") or "").strip()
                if candidate_id and candidate_id in available_id_set and candidate_id not in resolved_ids:
                    resolved_ids.append(candidate_id)
            return resolved_ids

        return []

    def agent_tools_credentials_list_payload(self, chat_id: str) -> dict[str, Any]:
        _chat, project = self._chat_and_project_for_agent_tools(chat_id)
        binding_payload = self.project_credential_binding_payload(str(project.get("id") or ""))
        return {
            "project_id": str(project.get("id") or ""),
            "repo_url": str(project.get("repo_url") or ""),
            "credential_binding": binding_payload["binding"],
            "available_credentials": binding_payload["available_credentials"],
            "effective_credential_ids": binding_payload["effective_credential_ids"],
        }

    def resolve_agent_tools_credentials(
        self,
        chat_id: str,
        mode: Any = PROJECT_CREDENTIAL_BINDING_MODE_AUTO,
        credential_ids: Any = None,
    ) -> dict[str, Any]:
        _chat, project = self._chat_and_project_for_agent_tools(chat_id)
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in PROJECT_CREDENTIAL_BINDING_MODES:
            supported = ", ".join(sorted(PROJECT_CREDENTIAL_BINDING_MODES))
            raise CredentialResolutionError(f"mode must be one of: {supported}.")
        submitted_ids = credential_ids if isinstance(credential_ids, list) else []
        selected_ids = self._resolve_agent_tools_credential_ids(project, normalized_mode, submitted_ids)
        resolved_credentials: list[dict[str, Any]] = []
        for credential_id in selected_ids:
            credential = self._credential_from_id(credential_id)
            if credential is None:
                continue
            resolved_credentials.append(
                self._materialize_agent_tool_credential(
                    credential,
                    context_key=f"agent_tools:{chat_id}:{credential_id}",
                )
            )
        return {
            "project_id": str(project.get("id") or ""),
            "repo_url": str(project.get("repo_url") or ""),
            "mode": normalized_mode,
            "credential_ids": selected_ids,
            "credentials": resolved_credentials,
        }

    def attach_agent_tools_project_credentials(
        self,
        chat_id: str,
        mode: Any,
        credential_ids: Any = None,
    ) -> dict[str, Any]:
        _chat, project = self._chat_and_project_for_agent_tools(chat_id)
        return self.attach_project_credentials(
            str(project.get("id") or ""),
            mode=mode,
            credential_ids=credential_ids if isinstance(credential_ids, list) else [],
            source=f"agent_tools:{chat_id}",
        )

    def _create_agent_tools_session(
        self,
        *,
        project_id: str = "",
        repo_url: str = "",
        credential_binding: dict[str, Any] | None = None,
        workspace: Path | None = None,
    ) -> tuple[str, str]:
        session_id = uuid.uuid4().hex
        token = _new_agent_tools_token()
        payload = {
            "id": session_id,
            "project_id": str(project_id or "").strip(),
            "repo_url": str(repo_url or "").strip(),
            "credential_binding": _normalize_project_credential_binding(credential_binding),
            "token_hash": _hash_agent_tools_token(token),
            "workspace": str(workspace) if workspace else "",
            "created_at": _iso_now(),
            "artifacts": [],
            "artifact_current_ids": [],
            "artifact_publish_token_hash": "",
            "ready_ack_guid": "",
            "ready_ack_stage": AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
            "ready_ack_at": "",
            "ready_ack_meta": {},
        }
        with self._agent_tools_sessions_lock:
            self._agent_tools_sessions[session_id] = payload
        return session_id, token

    def issue_agent_tools_session_ready_ack_guid(self, session_id: str) -> str:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise HTTPException(status_code=400, detail="session_id is required.")
        guid = _new_ready_ack_guid()
        with self._agent_tools_sessions_lock:
            session = self._agent_tools_sessions.get(normalized_session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="agent_tools session not found.")
            session["ready_ack_guid"] = guid
            session["ready_ack_stage"] = AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED
            session["ready_ack_at"] = ""
            session["ready_ack_meta"] = {}
            self._agent_tools_sessions[normalized_session_id] = session
        return guid

    def _agent_tools_session(self, session_id: str) -> dict[str, Any]:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            raise HTTPException(status_code=400, detail="session_id is required.")
        with self._agent_tools_sessions_lock:
            session = self._agent_tools_sessions.get(normalized_session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="agent_tools session not found.")
        return dict(session)

    def _remove_agent_tools_session(self, session_id: Any) -> None:
        normalized_session_id = str(session_id or "").strip()
        if not normalized_session_id:
            return
        with self._agent_tools_sessions_lock:
            self._agent_tools_sessions.pop(normalized_session_id, None)
        session_artifact_root = self._session_artifact_storage_root(normalized_session_id)
        if session_artifact_root.exists():
            self._delete_path(session_artifact_root)

    def require_agent_tools_session_token(self, session_id: str, token: Any) -> dict[str, Any]:
        session = self._agent_tools_session(session_id)
        expected_hash = str(session.get("token_hash") or "")
        if not expected_hash:
            raise HTTPException(status_code=409, detail="agent_tools session is not active.")
        submitted = str(token or "").strip()
        if not submitted:
            raise HTTPException(status_code=401, detail="Missing agent_tools token.")
        submitted_hash = _hash_agent_tools_token(submitted)
        if not submitted_hash or not hmac.compare_digest(submitted_hash, expected_hash):
            raise HTTPException(status_code=403, detail="Invalid agent_tools token.")
        return session

    def acknowledge_agent_tools_session_ready(
        self,
        session_id: str,
        *,
        token: Any,
        guid: Any,
        stage: Any = AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
        meta: Any = None,
    ) -> dict[str, Any]:
        session = self.require_agent_tools_session_token(session_id, token)
        resolved_guid = self._validated_ready_ack_guid(expected=session.get("ready_ack_guid"), submitted=guid)
        resolved_stage = _normalize_ready_ack_stage(stage)
        resolved_meta = meta if isinstance(meta, dict) else {}
        acknowledged_at = _iso_now()
        with self._agent_tools_sessions_lock:
            active = self._agent_tools_sessions.get(str(session_id))
            if active is None:
                raise HTTPException(status_code=404, detail="agent_tools session not found.")
            active["ready_ack_guid"] = resolved_guid
            active["ready_ack_stage"] = resolved_stage
            active["ready_ack_at"] = acknowledged_at
            active["ready_ack_meta"] = resolved_meta
            self._agent_tools_sessions[str(session_id)] = active
        return {
            "session_id": str(session_id),
            "guid": resolved_guid,
            "stage": resolved_stage,
            "acknowledged_at": acknowledged_at,
            "meta": resolved_meta,
        }

    def _agent_tools_project_context_from_session(self, session: dict[str, Any]) -> dict[str, Any]:
        project_id = str(session.get("project_id") or "").strip()
        if project_id:
            project = self.project(project_id)
            if project is not None:
                return dict(project)
        repo_url = str(session.get("repo_url") or "").strip()
        return {
            "id": project_id,
            "repo_url": repo_url,
            "credential_binding": _normalize_project_credential_binding(session.get("credential_binding")),
        }

    def agent_tools_session_credentials_list_payload(self, session_id: str) -> dict[str, Any]:
        session = self._agent_tools_session(session_id)
        project = self._agent_tools_project_context_from_session(session)
        binding = _normalize_project_credential_binding(project.get("credential_binding"))
        return {
            "project_id": str(project.get("id") or ""),
            "repo_url": str(project.get("repo_url") or ""),
            "credential_binding": binding,
            "available_credentials": self._project_available_credentials(project),
            "effective_credential_ids": self._resolve_agent_tools_credential_ids(
                project,
                binding["mode"],
                binding["credential_ids"],
            ),
        }

    def resolve_agent_tools_session_credentials(
        self,
        session_id: str,
        mode: Any = PROJECT_CREDENTIAL_BINDING_MODE_AUTO,
        credential_ids: Any = None,
    ) -> dict[str, Any]:
        session = self._agent_tools_session(session_id)
        project = self._agent_tools_project_context_from_session(session)
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in PROJECT_CREDENTIAL_BINDING_MODES:
            supported = ", ".join(sorted(PROJECT_CREDENTIAL_BINDING_MODES))
            raise CredentialResolutionError(f"mode must be one of: {supported}.")
        submitted_ids = credential_ids if isinstance(credential_ids, list) else []
        selected_ids = self._resolve_agent_tools_credential_ids(project, normalized_mode, submitted_ids)
        resolved_credentials: list[dict[str, Any]] = []
        for credential_id in selected_ids:
            credential = self._credential_from_id(credential_id)
            if credential is None:
                continue
            resolved_credentials.append(
                self._materialize_agent_tool_credential(
                    credential,
                    context_key=f"agent_tools_session:{session_id}:{credential_id}",
                )
            )
        return {
            "project_id": str(project.get("id") or ""),
            "repo_url": str(project.get("repo_url") or ""),
            "mode": normalized_mode,
            "credential_ids": selected_ids,
            "credentials": resolved_credentials,
        }

    def attach_agent_tools_session_project_credentials(
        self,
        session_id: str,
        mode: Any,
        credential_ids: Any = None,
    ) -> dict[str, Any]:
        session = self._agent_tools_session(session_id)
        project_id = str(session.get("project_id") or "").strip()
        if not project_id:
            project = self._agent_tools_project_context_from_session(session)
            requested_ids = credential_ids if isinstance(credential_ids, list) else []
            binding = _normalize_project_credential_binding(
                {
                    "mode": mode,
                    "credential_ids": requested_ids,
                    "source": f"agent_tools_session:{session_id}",
                    "updated_at": _iso_now(),
                }
            )
            available_credentials = self._project_available_credentials(project)
            available_ids = {
                str(entry.get("credential_id") or "").strip()
                for entry in available_credentials
                if str(entry.get("credential_id") or "").strip()
            }
            if binding["mode"] in {PROJECT_CREDENTIAL_BINDING_MODE_SET, PROJECT_CREDENTIAL_BINDING_MODE_SINGLE}:
                filtered_ids = [credential_id for credential_id in binding["credential_ids"] if credential_id in available_ids]
                if not filtered_ids:
                    raise HTTPException(status_code=400, detail="No valid credentials were provided for this repository.")
                binding["credential_ids"] = (
                    filtered_ids[:1] if binding["mode"] == PROJECT_CREDENTIAL_BINDING_MODE_SINGLE else filtered_ids
                )
            else:
                binding["credential_ids"] = []

            project["credential_binding"] = binding
            effective_ids = self._resolve_agent_tools_credential_ids(
                project,
                binding["mode"],
                binding["credential_ids"],
            )
            with self._agent_tools_sessions_lock:
                active_session = self._agent_tools_sessions.get(session_id)
                if active_session is not None:
                    active_session["credential_binding"] = binding
                    self._agent_tools_sessions[session_id] = active_session

            return {
                "project_id": "",
                "binding": binding,
                "available_credentials": available_credentials,
                "effective_credential_ids": effective_ids,
            }
        return self.attach_project_credentials(
            project_id=project_id,
            mode=mode,
            credential_ids=credential_ids if isinstance(credential_ids, list) else [],
            source=f"agent_tools_session:{session_id}",
        )

    def list_chat_artifacts(self, chat_id: str) -> list[dict[str, Any]]:
        chat = self.chat(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        artifacts = _normalize_chat_artifacts(chat.get("artifacts"))
        return [self._chat_artifact_public_payload(chat_id, artifact) for artifact in reversed(artifacts)]

    def _chat_artifact_storage_root(self, chat_id: str) -> Path:
        return self.chat_artifacts_dir / str(chat_id)

    def _session_artifact_storage_root(self, session_id: str) -> Path:
        return self.session_artifacts_dir / str(session_id)

    def _persist_artifact_file_copy(
        self,
        *,
        source_file: Path,
        storage_root: Path,
        artifact_id: str,
        relative_path: str,
    ) -> tuple[str, int]:
        storage_entry_name = _normalize_artifact_name("", fallback=Path(relative_path).name)
        artifact_storage_dir = storage_root / artifact_id
        if artifact_storage_dir.exists():
            self._delete_path(artifact_storage_dir)
        try:
            artifact_storage_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create artifact storage directory: {artifact_storage_dir}",
            ) from exc

        destination = artifact_storage_dir / storage_entry_name
        temporary_destination = artifact_storage_dir / f".{storage_entry_name}.tmp-{uuid.uuid4().hex}"
        try:
            with source_file.open("rb") as src_handle, temporary_destination.open("wb") as dst_handle:
                shutil.copyfileobj(src_handle, dst_handle, length=1024 * 1024)
            os.replace(temporary_destination, destination)
            size_bytes = int(destination.stat().st_size)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to persist artifact file copy: {source_file}") from exc
        finally:
            if temporary_destination.exists():
                try:
                    temporary_destination.unlink()
                except OSError:
                    pass

        try:
            storage_relative = destination.resolve().relative_to(self.artifacts_dir.resolve()).as_posix()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="Artifact storage path escaped managed directory.") from exc
        normalized_storage_relative = _coerce_artifact_relative_path(storage_relative)
        if not normalized_storage_relative:
            raise HTTPException(status_code=500, detail="Artifact storage path is invalid.")
        return normalized_storage_relative, size_bytes

    def _upsert_chat_artifact_from_file(
        self,
        *,
        state: dict[str, Any],
        chat_id: str,
        chat: dict[str, Any],
        file_path: Path,
        relative_path: str,
        name: Any = None,
    ) -> dict[str, Any]:
        now = _iso_now()
        artifacts = _normalize_chat_artifacts(chat.get("artifacts"))
        normalized_name = _normalize_artifact_name(name, fallback=file_path.name)

        existing_index = -1
        for index, artifact in enumerate(artifacts):
            if str(artifact.get("relative_path") or "") == relative_path:
                existing_index = index
                break

        artifact_id = (
            str(artifacts[existing_index].get("id") or "") or uuid.uuid4().hex
            if existing_index >= 0
            else uuid.uuid4().hex
        )
        storage_relative_path, persisted_size_bytes = self._persist_artifact_file_copy(
            source_file=file_path,
            storage_root=self._chat_artifact_storage_root(chat_id),
            artifact_id=artifact_id,
            relative_path=relative_path,
        )
        stored_artifact = {
            "id": artifact_id,
            "name": normalized_name,
            "relative_path": relative_path,
            "storage_relative_path": storage_relative_path,
            "size_bytes": int(persisted_size_bytes),
            "created_at": now,
        }

        if existing_index >= 0:
            artifacts[existing_index] = stored_artifact
        else:
            artifacts.append(stored_artifact)
            if len(artifacts) > CHAT_ARTIFACTS_MAX_ITEMS:
                artifacts = artifacts[-CHAT_ARTIFACTS_MAX_ITEMS:]

        current_ids = _normalize_chat_current_artifact_ids(chat.get("artifact_current_ids"), artifacts)
        if artifact_id and artifact_id not in current_ids:
            current_ids.append(artifact_id)
        if len(current_ids) > CHAT_ARTIFACTS_MAX_ITEMS:
            current_ids = current_ids[-CHAT_ARTIFACTS_MAX_ITEMS:]

        chat["artifacts"] = artifacts
        chat["artifact_current_ids"] = current_ids
        chat["artifact_prompt_history"] = _normalize_chat_artifact_prompt_history(chat.get("artifact_prompt_history"))
        chat["updated_at"] = now
        state["chats"][chat_id] = chat
        return stored_artifact

    def _upsert_session_artifact_from_file(
        self,
        *,
        session_id: str,
        session: dict[str, Any],
        file_path: Path,
        relative_path: str,
        name: Any = None,
    ) -> dict[str, Any]:
        now = _iso_now()
        artifacts = _normalize_chat_artifacts(session.get("artifacts"))
        normalized_name = _normalize_artifact_name(name, fallback=file_path.name)

        existing_index = -1
        for index, artifact in enumerate(artifacts):
            if str(artifact.get("relative_path") or "") == relative_path:
                existing_index = index
                break

        artifact_id = (
            str(artifacts[existing_index].get("id") or "") or uuid.uuid4().hex
            if existing_index >= 0
            else uuid.uuid4().hex
        )
        storage_relative_path, persisted_size_bytes = self._persist_artifact_file_copy(
            source_file=file_path,
            storage_root=self._session_artifact_storage_root(session_id),
            artifact_id=artifact_id,
            relative_path=relative_path,
        )
        stored_artifact = {
            "id": artifact_id,
            "name": normalized_name,
            "relative_path": relative_path,
            "storage_relative_path": storage_relative_path,
            "size_bytes": int(persisted_size_bytes),
            "created_at": now,
        }

        if existing_index >= 0:
            artifacts[existing_index] = stored_artifact
        else:
            artifacts.append(stored_artifact)
            if len(artifacts) > CHAT_ARTIFACTS_MAX_ITEMS:
                artifacts = artifacts[-CHAT_ARTIFACTS_MAX_ITEMS:]

        current_ids = _normalize_chat_current_artifact_ids(session.get("artifact_current_ids"), artifacts)
        if artifact_id and artifact_id not in current_ids:
            current_ids.append(artifact_id)
        if len(current_ids) > CHAT_ARTIFACTS_MAX_ITEMS:
            current_ids = current_ids[-CHAT_ARTIFACTS_MAX_ITEMS:]

        with self._agent_tools_sessions_lock:
            active_session = self._agent_tools_sessions.get(session_id)
            if active_session is not None:
                active_session["artifacts"] = artifacts
                active_session["artifact_current_ids"] = current_ids
                self._agent_tools_sessions[session_id] = active_session

        return stored_artifact

    def publish_chat_artifact(
        self,
        chat_id: str,
        token: Any,
        submitted_path: Any,
        name: Any = None,
    ) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._require_artifact_publish_token(chat, token)

        file_path, relative_path = self._resolve_chat_artifact_file(chat_id, submitted_path)
        stored_artifact = self._upsert_chat_artifact_from_file(
            state=state,
            chat_id=chat_id,
            chat=chat,
            file_path=file_path,
            relative_path=relative_path,
            name=name,
        )
        self.save(state, reason="chat_artifact_published")
        return self._chat_artifact_public_payload(chat_id, stored_artifact)

    def submit_chat_artifact(
        self,
        chat_id: str,
        token: Any,
        submitted_path: Any,
        name: Any = None,
    ) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        self._require_agent_tools_token(chat, token)

        file_path, relative_path = self._resolve_chat_artifact_file(chat_id, submitted_path)
        stored_artifact = self._upsert_chat_artifact_from_file(
            state=state,
            chat_id=chat_id,
            chat=chat,
            file_path=file_path,
            relative_path=relative_path,
            name=name,
        )
        self.save(state, reason="chat_artifact_submitted")
        return self._chat_artifact_public_payload(chat_id, stored_artifact)

    def publish_session_artifact(
        self,
        session_id: str,
        token: Any,
        submitted_path: Any,
        name: Any = None,
    ) -> dict[str, Any]:
        session = self._agent_tools_session(session_id)
        self._require_session_artifact_publish_token(session, token)

        workspace = Path(str(session.get("workspace") or "")).resolve()
        if not workspace or not workspace.exists():
            raise HTTPException(status_code=409, detail="Session workspace is unavailable.")

        file_path, relative_path = self._resolve_artifact_file_in_workspace(workspace, submitted_path)
        stored_artifact = self._upsert_session_artifact_from_file(
            session_id=session_id,
            session=session,
            file_path=file_path,
            relative_path=relative_path,
            name=name,
        )
        return self._session_artifact_public_payload(session_id, stored_artifact)

    def submit_session_artifact(
        self,
        session_id: str,
        token: Any,
        submitted_path: Any,
        name: Any = None,
    ) -> dict[str, Any]:
        session = self.require_agent_tools_session_token(session_id, token)
        workspace = Path(str(session.get("workspace") or "")).resolve()
        if not workspace or not workspace.exists():
            raise HTTPException(status_code=409, detail="Session workspace is unavailable.")

        file_path, relative_path = self._resolve_artifact_file_in_workspace(workspace, submitted_path)
        stored_artifact = self._upsert_session_artifact_from_file(
            session_id=session_id,
            session=session,
            file_path=file_path,
            relative_path=relative_path,
            name=name,
        )
        return self._session_artifact_public_payload(session_id, stored_artifact)

    def _resolve_artifact_file_in_workspace(self, workspace: Path, submitted_path: Any) -> tuple[Path, str]:
        normalized_path = str(submitted_path or "").strip()
        if not normalized_path:
            raise HTTPException(status_code=400, detail="path is required.")

        raw_candidate = Path(normalized_path).expanduser()
        candidate = raw_candidate.resolve() if raw_candidate.is_absolute() else (workspace / raw_candidate).resolve()

        if not candidate.exists():
            LOGGER.warning(
                "Artifact file not found in workspace: workspace=%s raw_path=%s candidate=%s",
                workspace,
                normalized_path,
                candidate,
            )
            raise HTTPException(status_code=404, detail=f"Artifact file not found: {normalized_path}")
        if not candidate.is_file():
            LOGGER.warning(
                "Artifact path is not a file in workspace: workspace=%s raw_path=%s candidate=%s",
                workspace,
                normalized_path,
                candidate,
            )
            raise HTTPException(status_code=400, detail=f"Artifact path is not a file: {normalized_path}")

        try:
            relative_path_value = candidate.relative_to(workspace).as_posix()
        except ValueError:
            # Keep outside-workspace submissions uniquely identifiable in artifact history.
            relative_path_value = f"external/{candidate.as_posix()}"
        relative_path = _coerce_artifact_relative_path(relative_path_value)
        if not relative_path:
            LOGGER.warning(
                "Artifact path normalized to empty in workspace: workspace=%s raw_path=%s candidate=%s",
                workspace,
                normalized_path,
                candidate,
            )
            raise HTTPException(status_code=400, detail="Artifact path is invalid.")
        return candidate, relative_path

    def _session_artifact_public_payload(self, session_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(artifact.get("id") or "")
        return {
            "id": artifact_id,
            "name": _normalize_artifact_name(artifact.get("name"), fallback=Path(str(artifact.get("relative_path") or "")).name),
            "relative_path": str(artifact.get("relative_path") or ""),
            "size_bytes": int(artifact.get("size_bytes") or 0),
            "created_at": str(artifact.get("created_at") or ""),
            "preview_url": self._session_artifact_preview_url(session_id, artifact_id),
            "download_url": self._session_artifact_download_url(session_id, artifact_id),
        }

    def _session_artifact_publish_url(self, session_id: str) -> str:
        return f"{self.artifact_publish_base_url}/api/agent-tools/sessions/{session_id}/artifacts/publish"

    def _session_artifact_download_url(self, session_id: str, artifact_id: str) -> str:
        return f"/api/agent-tools/sessions/{session_id}/artifacts/{artifact_id}/download"

    def _session_artifact_preview_url(self, session_id: str, artifact_id: str) -> str:
        return f"/api/agent-tools/sessions/{session_id}/artifacts/{artifact_id}/preview"

    def _resolve_persisted_artifact_path(self, artifact: dict[str, Any]) -> Path | None:
        storage_relative_path = _coerce_artifact_relative_path(artifact.get("storage_relative_path"))
        if not storage_relative_path:
            return None
        artifacts_root = self.artifacts_dir.resolve()
        resolved = (artifacts_root / storage_relative_path).resolve()
        try:
            resolved.relative_to(artifacts_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Artifact path is invalid.") from exc
        if not resolved.exists() or not resolved.is_file():
            return None
        return resolved

    def resolve_session_artifact_download(self, session_id: str, artifact_id: str) -> tuple[Path, str, str]:
        session = self._agent_tools_session(session_id)
        normalized_artifact_id = str(artifact_id or "").strip()
        if not normalized_artifact_id:
            raise HTTPException(status_code=400, detail="artifact_id is required.")

        artifacts = _normalize_chat_artifacts(session.get("artifacts"))
        match = next((entry for entry in artifacts if str(entry.get("id") or "") == normalized_artifact_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Artifact not found.")

        resolved = self._resolve_persisted_artifact_path(match)
        if resolved is None:
            workspace = Path(str(session.get("workspace") or "")).resolve()
            if not workspace or not workspace.exists():
                raise HTTPException(status_code=409, detail="Session workspace is unavailable.")

            resolved = (workspace / str(match.get("relative_path") or "")).resolve()
            try:
                resolved.relative_to(workspace)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Artifact path is invalid.") from exc
            if not resolved.exists() or not resolved.is_file():
                raise HTTPException(status_code=404, detail="Artifact file is no longer available.")

        filename = _normalize_artifact_name(match.get("name"), fallback=resolved.name)
        media_type = (
            mimetypes.guess_type(filename)[0]
            or mimetypes.guess_type(resolved.name)[0]
            or "application/octet-stream"
        )
        return resolved, filename, media_type

    def resolve_session_artifact_preview(self, session_id: str, artifact_id: str) -> tuple[Path, str]:
        artifact_path, _filename, media_type = self.resolve_session_artifact_download(session_id, artifact_id)
        return artifact_path, media_type

    def resolve_chat_artifact_download(self, chat_id: str, artifact_id: str) -> tuple[Path, str, str]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        normalized_artifact_id = str(artifact_id or "").strip()
        if not normalized_artifact_id:
            raise HTTPException(status_code=400, detail="artifact_id is required.")

        artifacts = _normalize_chat_artifacts(chat.get("artifacts"))
        match = next((entry for entry in artifacts if str(entry.get("id") or "") == normalized_artifact_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Artifact not found.")

        resolved = self._resolve_persisted_artifact_path(match)
        if resolved is None:
            workspace = self.chat_workdir(chat_id).resolve()
            resolved = (workspace / str(match.get("relative_path") or "")).resolve()
            try:
                resolved.relative_to(workspace)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Artifact path is invalid.") from exc
            if not resolved.exists() or not resolved.is_file():
                raise HTTPException(status_code=404, detail="Artifact file is no longer available.")

        filename = _normalize_artifact_name(match.get("name"), fallback=resolved.name)
        media_type = (
            mimetypes.guess_type(filename)[0]
            or mimetypes.guess_type(resolved.name)[0]
            or "application/octet-stream"
        )
        return resolved, filename, media_type

    def resolve_chat_artifact_preview(self, chat_id: str, artifact_id: str) -> tuple[Path, str]:
        artifact_path, _filename, media_type = self.resolve_chat_artifact_download(chat_id, artifact_id)
        return artifact_path, media_type

    def project(self, project_id: str) -> dict[str, Any] | None:
        return self.load()["projects"].get(project_id)

    def chat(self, chat_id: str) -> dict[str, Any] | None:
        return self.load()["chats"].get(chat_id)

    def list_projects(self) -> list[dict[str, Any]]:
        return list(self.load()["projects"].values())

    def list_chats(self) -> list[dict[str, Any]]:
        return list(self.load()["chats"].values())

    def add_project(
        self,
        repo_url: str,
        name: str | None = None,
        default_branch: str | None = None,
        setup_script: str | None = None,
        base_image_mode: str | None = None,
        base_image_value: str | None = None,
        default_ro_mounts: list[str] | None = None,
        default_rw_mounts: list[str] | None = None,
        default_env_vars: list[str] | None = None,
        credential_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_repo_url = str(repo_url or "").strip()
        validation_error = _project_repo_url_validation_error(normalized_repo_url)
        if validation_error:
            raise HTTPException(status_code=400, detail=validation_error)

        state = self.load()
        project_id = uuid.uuid4().hex
        project_name = name or _extract_repo_name(normalized_repo_url)
        normalized_binding = self._auto_discover_project_credential_binding(
            normalized_repo_url,
            credential_binding=credential_binding,
        )
        normalized_env_vars = self._dedupe_entries(default_env_vars or [])
        auth_env_vars = self._recommended_auth_env_vars_for_repo(
            normalized_repo_url,
            credential_binding=normalized_binding,
        )
        existing_env_keys = {
            str(entry).split("=", 1)[0].strip().upper()
            for entry in normalized_env_vars
            if "=" in str(entry)
        }
        github_token_value = ""
        for entry in normalized_env_vars:
            raw = str(entry)
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            normalized_key = key.strip().upper()
            if normalized_key in {"GITHUB_TOKEN", "GH_TOKEN"} and value:
                github_token_value = value
                break
        if not github_token_value:
            for entry in auth_env_vars:
                raw = str(entry)
                if "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                normalized_key = key.strip().upper()
                if normalized_key in {"GITHUB_TOKEN", "GH_TOKEN"} and value:
                    github_token_value = value
                    break
        if github_token_value:
            if "GITHUB_TOKEN" not in existing_env_keys:
                normalized_env_vars.append(f"GITHUB_TOKEN={github_token_value}")
                existing_env_keys.add("GITHUB_TOKEN")
            if "GH_TOKEN" not in existing_env_keys:
                normalized_env_vars.append(f"GH_TOKEN={github_token_value}")
                existing_env_keys.add("GH_TOKEN")
        for auth_env in auth_env_vars:
            auth_key = str(auth_env).split("=", 1)[0].strip().upper()
            if auth_key in {"GITHUB_TOKEN", "GH_TOKEN"}:
                continue
            if auth_key and auth_key not in existing_env_keys:
                normalized_env_vars.append(auth_env)
                existing_env_keys.add(auth_key)
        resolved_default_branch = str(default_branch or "").strip()
        if not resolved_default_branch:
            git_env = self._github_git_env_for_repo(
                normalized_repo_url,
                project={"repo_url": normalized_repo_url, "credential_binding": normalized_binding},
            )
            resolved_default_branch = _detect_default_branch(normalized_repo_url, env=git_env)
        normalized_base_mode = _normalize_base_image_mode(base_image_mode)
        normalized_base_value = _normalize_base_image_value(normalized_base_mode, base_image_value)
        if normalized_base_mode == "repo_path" and not normalized_base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )
        project = {
            "id": project_id,
            "name": project_name,
            "repo_url": normalized_repo_url,
            "setup_script": setup_script or "",
            "base_image_mode": normalized_base_mode,
            "base_image_value": normalized_base_value,
            "default_ro_mounts": default_ro_mounts or [],
            "default_rw_mounts": default_rw_mounts or [],
            "default_env_vars": normalized_env_vars,
            "default_branch": resolved_default_branch,
            "created_at": _iso_now(),
            "updated_at": _iso_now(),
            "setup_snapshot_image": "",
            "build_status": "pending",
            "build_error": "",
            "build_started_at": "",
            "build_finished_at": "",
            "credential_binding": normalized_binding,
        }
        state["projects"][project_id] = project
        self.save(state)
        self._schedule_project_build(project_id)
        return self.load()["projects"][project_id]

    def update_project(self, project_id: str, update: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        for field in [
            "setup_script",
            "default_branch",
            "name",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
            "credential_binding",
        ]:
            if field in update:
                project[field] = update[field]
        normalized_base_mode = _normalize_base_image_mode(project.get("base_image_mode"))
        normalized_base_value = _normalize_base_image_value(normalized_base_mode, project.get("base_image_value"))
        if normalized_base_mode == "repo_path" and not normalized_base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )
        project["base_image_mode"] = normalized_base_mode
        project["base_image_value"] = normalized_base_value

        snapshot_fields = {
            "setup_script",
            "default_branch",
            "base_image_mode",
            "base_image_value",
            "default_ro_mounts",
            "default_rw_mounts",
            "default_env_vars",
        }
        requires_rebuild = any(field in update for field in snapshot_fields)
        if requires_rebuild:
            project["setup_snapshot_image"] = ""
            project["repo_head_sha"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""

        project["updated_at"] = _iso_now()
        state["projects"][project_id] = project
        self.save(state)
        if requires_rebuild:
            self._schedule_project_build(project_id)
            return self.load()["projects"][project_id]
        return self.load()["projects"][project_id]

    def _project_available_credentials(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        repo_host = _git_repo_host(str(project.get("repo_url") or ""))
        if not repo_host:
            return []
        host_credentials: list[dict[str, Any]] = []
        for credential in self._credential_catalog():
            credential_host = str(credential.get("host") or "").strip().lower()
            if credential_host != repo_host:
                continue
            host_credentials.append(dict(credential))
        return host_credentials

    def _resolved_project_credential_ids(self, project: dict[str, Any]) -> list[str]:
        binding = _normalize_project_credential_binding(project.get("credential_binding"))
        available = self._project_available_credentials(project)
        available_ids = [str(entry.get("credential_id") or "").strip() for entry in available if str(entry.get("credential_id") or "").strip()]
        available_id_set = set(available_ids)

        if binding["mode"] in {PROJECT_CREDENTIAL_BINDING_MODE_SET, PROJECT_CREDENTIAL_BINDING_MODE_SINGLE}:
            selected = [credential_id for credential_id in binding["credential_ids"] if credential_id in available_id_set]
            if binding["mode"] == PROJECT_CREDENTIAL_BINDING_MODE_SINGLE and selected:
                return selected[:1]
            return selected
        if binding["mode"] == PROJECT_CREDENTIAL_BINDING_MODE_ALL:
            return available_ids
        return []

    def project_credential_binding_payload(self, project_id: str) -> dict[str, Any]:
        project = self.project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        binding = _normalize_project_credential_binding(project.get("credential_binding"))
        return {
            "project_id": project_id,
            "binding": binding,
            "available_credentials": self._project_available_credentials(project),
            "effective_credential_ids": self._resolved_project_credential_ids(project),
        }

    def attach_project_credentials(
        self,
        project_id: str,
        mode: Any,
        credential_ids: Any = None,
        source: str = "agent_tools",
    ) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        requested_ids = credential_ids if isinstance(credential_ids, list) else []
        binding = _normalize_project_credential_binding(
            {
                "mode": mode,
                "credential_ids": requested_ids,
                "source": source,
                "updated_at": _iso_now(),
            }
        )
        available_ids = {
            str(entry.get("credential_id") or "").strip()
            for entry in self._project_available_credentials(project)
            if str(entry.get("credential_id") or "").strip()
        }
        if binding["mode"] in {PROJECT_CREDENTIAL_BINDING_MODE_SET, PROJECT_CREDENTIAL_BINDING_MODE_SINGLE}:
            filtered = [credential_id for credential_id in binding["credential_ids"] if credential_id in available_ids]
            if not filtered:
                raise HTTPException(status_code=400, detail="No valid credentials were provided for this project.")
            binding["credential_ids"] = filtered[:1] if binding["mode"] == PROJECT_CREDENTIAL_BINDING_MODE_SINGLE else filtered
        else:
            binding["credential_ids"] = []

        project["credential_binding"] = binding
        project["updated_at"] = _iso_now()
        state["projects"][project_id] = project
        self.save(state, reason="project_credential_binding_updated")
        self._emit_state_changed(reason="project_credential_binding_updated")
        return self.project_credential_binding_payload(project_id)

    def _start_project_build_thread_locked(self, project_id: str) -> None:
        thread = self._project_build_threads.get(project_id)
        if thread and thread.is_alive():
            return
        thread = Thread(target=self._project_build_worker, args=(project_id,), daemon=True)
        self._project_build_threads[project_id] = thread
        thread.start()

    def _schedule_project_build(self, project_id: str) -> None:
        self._register_project_build_request(project_id)
        with self._project_build_lock:
            self._start_project_build_thread_locked(project_id)

    def _project_build_worker(self, project_id: str) -> None:
        try:
            while True:
                if self._is_project_build_cancelled(project_id):
                    self._mark_project_build_cancelled(project_id)
                    return
                state = self.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                build_status = str(project.get("build_status") or "")
                if build_status not in {"pending", "building"}:
                    return
                self._build_project_snapshot(project_id)
                state = self.load()
                project = state["projects"].get(project_id)
                if project is None:
                    return
                expected = self._project_setup_snapshot_tag(project)
                snapshot = str(project.get("setup_snapshot_image") or "").strip()
                status = str(project.get("build_status") or "")
                if status == "ready" and snapshot == expected and _docker_image_exists(snapshot):
                    return
                if status == "pending":
                    if self._is_project_build_cancelled(project_id):
                        self._mark_project_build_cancelled(project_id)
                        return
                    continue
                if status == "ready" and snapshot != expected:
                    project["build_status"] = "pending"
                    project["updated_at"] = _iso_now()
                    state["projects"][project_id] = project
                    self.save(state)
                    continue
                return
        finally:
            with self._project_build_lock:
                existing = self._project_build_threads.get(project_id)
                if existing is not None and existing.ident == current_thread().ident:
                    self._project_build_threads.pop(project_id, None)
                    state = self.load()
                    project = state["projects"].get(project_id)
                    if project is not None and str(project.get("build_status") or "") in {"pending", "building"}:
                        self._start_project_build_thread_locked(project_id)
            self._clear_project_build_request(project_id)

    def _build_project_snapshot(self, project_id: str) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            self._clear_project_build_request(project_id)
            raise HTTPException(status_code=404, detail="Project not found.")
        if self._is_project_build_cancelled(project_id):
            self._mark_project_build_cancelled(project_id)
            self._clear_project_build_request(project_id)
            current_project = self.project(project_id)
            if current_project is None:
                raise HTTPException(status_code=404, detail="Project not found.")
            return current_project

        started_at = _iso_now()
        project["build_status"] = "building"
        project["build_error"] = ""
        project["build_started_at"] = started_at
        project["build_finished_at"] = ""
        project["updated_at"] = started_at
        state["projects"][project_id] = project
        self.save(state, reason="project_build_started")

        project_copy = dict(project)
        log_path = self.project_build_log(project_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("", encoding="utf-8")
        self._emit_project_build_log(project_id, "", replace=True)

        try:
            snapshot_tag = self._prepare_project_snapshot_for_project(project_copy, log_path=log_path)
            LOGGER.debug("Project build snapshot command succeeded for project=%s snapshot=%s", project_id, snapshot_tag)
        except Exception as exc:
            state = self.load()
            current = state["projects"].get(project_id)
            if current is None:
                self._clear_project_build_request(project_id)
                raise
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            now = _iso_now()
            is_cancelled = self._is_project_build_cancelled(project_id)
            current["build_status"] = "cancelled" if is_cancelled else "failed"
            current["build_error"] = PROJECT_BUILD_CANCELLED_ERROR if is_cancelled else str(detail)
            current["build_finished_at"] = now
            current["updated_at"] = now
            state["projects"][project_id] = current
            if is_cancelled:
                self.save(state, reason="project_build_cancelled")
                LOGGER.info("Project build cancelled for project=%s", project_id)
            else:
                self.save(state, reason="project_build_failed")
                LOGGER.warning("Project build failed for project=%s: %s", project_id, detail)
            self._clear_project_build_request(project_id)
            return current

        state = self.load()
        current = state["projects"].get(project_id)
        if current is None:
            self._clear_project_build_request(project_id)
            raise HTTPException(status_code=404, detail="Project not found.")
        if self._is_project_build_cancelled(project_id):
            now = _iso_now()
            current["build_status"] = "cancelled"
            current["build_error"] = PROJECT_BUILD_CANCELLED_ERROR
            current["build_finished_at"] = now
            current["updated_at"] = now
            state["projects"][project_id] = current
            self.save(state, reason="project_build_cancelled")
            self._clear_project_build_request(project_id)
            return current
        current_candidate = dict(current)
        current_candidate["repo_head_sha"] = project_copy.get("repo_head_sha") or ""
        expected_snapshot = self._project_setup_snapshot_tag(current_candidate)
        if snapshot_tag != expected_snapshot:
            current["setup_snapshot_image"] = ""
            current["repo_head_sha"] = ""
            current.pop("snapshot_updated_at", None)
            current["build_status"] = "pending"
            current["build_error"] = ""
            current["build_started_at"] = ""
            current["build_finished_at"] = ""
            current["updated_at"] = _iso_now()
            state["projects"][project_id] = current
            self.save(state, reason="project_build_superseded")
            LOGGER.debug(
                "Project build output superseded for project=%s built=%s expected=%s; keeping project pending",
                project_id,
                snapshot_tag,
                expected_snapshot,
            )
            return current
        current["setup_snapshot_image"] = snapshot_tag
        current["repo_head_sha"] = project_copy.get("repo_head_sha") or ""
        current["snapshot_updated_at"] = _iso_now()
        current["build_status"] = "ready"
        current["build_error"] = ""
        current["build_finished_at"] = _iso_now()
        current["updated_at"] = _iso_now()
        state["projects"][project_id] = current
        self.save(state, reason="project_build_ready")
        LOGGER.debug("Project build completed for project=%s snapshot=%s", project_id, snapshot_tag)
        self._clear_project_build_request(project_id)
        return current

    def delete_project(self, project_id: str) -> None:
        state = self.load()
        if project_id not in state["projects"]:
            raise HTTPException(status_code=404, detail="Project not found.")

        process_to_cancel: subprocess.Popen[str] | None = None
        with self._project_build_requests_lock:
            request_state = self._project_build_requests.pop(project_id, None)
            if request_state is not None:
                process_to_cancel = request_state.process
        if process_to_cancel is not None and _is_process_running(process_to_cancel.pid):
            _stop_process(process_to_cancel.pid)

        project_chats = [chat for chat in self.list_chats() if chat["project_id"] == project_id]
        for chat in project_chats:
            self.delete_chat(chat["id"], state=state)

        project_workspace = self.project_workdir(project_id)
        if project_workspace.exists():
            self._delete_path(project_workspace)
        project_log = self.project_build_log(project_id)
        if project_log.exists():
            project_log.unlink()

        del state["projects"][project_id]
        self.save(state)

    def create_chat(
        self,
        project_id: str,
        profile: str | None,
        ro_mounts: list[str],
        rw_mounts: list[str],
        env_vars: list[str],
        agent_args: list[str] | None = None,
        agent_type: str | None = None,
        create_request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")

        chat_id = uuid.uuid4().hex
        now = _iso_now()
        sanitized_project_name = _sanitize_workspace_component(project.get("name") or project_id)
        workspace_path = self.chat_dir / f"{sanitized_project_name}_{chat_id}"
        container_workspace = _container_workspace_path_for_project(project.get("name") or project_id)
        chat = {
            "id": chat_id,
            "project_id": project_id,
            "name": CHAT_DEFAULT_NAME,
            "profile": profile or "",
            "ro_mounts": ro_mounts,
            "rw_mounts": rw_mounts,
            "env_vars": env_vars,
            "agent_args": agent_args or [],
            "agent_type": _resolve_optional_chat_agent_type(
                agent_type,
                default_value=self.default_chat_agent_type(),
            ),
            "status": CHAT_STATUS_STOPPED,
            "status_reason": CHAT_STATUS_REASON_CHAT_CREATED,
            "last_status_transition_at": now,
            "start_error": "",
            "last_exit_code": None,
            "last_exit_at": "",
            "stop_requested_at": "",
            "pid": None,
            "workspace": str(workspace_path),
            "container_workspace": container_workspace,
            "title_user_prompts": [],
            "title_cached": "",
            "title_prompt_fingerprint": "",
            "title_source": "openai",
            "title_status": "idle",
            "title_error": "",
            "artifacts": [],
            "artifact_current_ids": [],
            "artifact_prompt_history": [],
            "artifact_publish_token_hash": "",
            "artifact_publish_token_issued_at": "",
            "agent_tools_token_hash": "",
            "agent_tools_token_issued_at": "",
            "ready_ack_guid": "",
            "ready_ack_stage": AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED,
            "ready_ack_at": "",
            "ready_ack_meta": {},
            "create_request_id": _compact_whitespace(str(create_request_id or "")).strip(),
            "created_at": now,
            "updated_at": now,
        }
        state["chats"][chat_id] = chat
        self.save(state, reason=CHAT_STATUS_REASON_CHAT_CREATED)
        LOGGER.info(
            "Chat state transition chat_id=%s from=%s to=%s reason=%s",
            chat_id,
            "missing",
            CHAT_STATUS_STOPPED,
            CHAT_STATUS_REASON_CHAT_CREATED,
        )
        return chat

    def create_and_start_chat(
        self,
        project_id: str,
        agent_args: list[str] | None = None,
        agent_type: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        state = self.load()
        project = state["projects"].get(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        build_status = str(project.get("build_status") or "")
        if build_status != "ready":
            raise HTTPException(status_code=409, detail="Project image is still being built. Save settings and wait.")
        normalized_agent_args = [str(arg) for arg in (agent_args or []) if str(arg).strip()]
        resolved_agent_type = (
            self.default_chat_agent_type()
            if agent_type is None
            else _normalize_chat_agent_type(agent_type, strict=True)
        )
        normalized_agent_args = _apply_default_model_for_agent(
            resolved_agent_type,
            normalized_agent_args,
            self.runtime_config,
        )
        normalized_request_id = _compact_whitespace(str(request_id or "")).strip()
        if normalized_request_id:
            existing_chat = self._chat_for_create_request(
                state=state,
                project_id=project_id,
                request_id=normalized_request_id,
            )
            if existing_chat is not None:
                LOGGER.info(
                    "Reused existing chat for create request project_id=%s request_id=%s chat_id=%s",
                    project_id,
                    normalized_request_id,
                    existing_chat.get("id"),
                )
                return existing_chat
        create_chat_kwargs: dict[str, Any] = {
            "profile": "",
            "ro_mounts": list(project.get("default_ro_mounts") or []),
            "rw_mounts": list(project.get("default_rw_mounts") or []),
            "env_vars": list(project.get("default_env_vars") or []),
            "agent_args": normalized_agent_args,
            "agent_type": resolved_agent_type,
        }
        if normalized_request_id:
            create_chat_kwargs["create_request_id"] = normalized_request_id
        chat = self.create_chat(
            project_id,
            **create_chat_kwargs,
        )
        return self.start_chat(chat["id"])

    @staticmethod
    def _chat_for_create_request(
        state: dict[str, Any],
        project_id: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        normalized_project_id = str(project_id or "").strip()
        normalized_request_id = _compact_whitespace(str(request_id or "")).strip()
        if not normalized_project_id or not normalized_request_id:
            return None
        for chat in state.get("chats", {}).values():
            if not isinstance(chat, dict):
                continue
            if str(chat.get("project_id") or "").strip() != normalized_project_id:
                continue
            if _compact_whitespace(str(chat.get("create_request_id") or "")).strip() != normalized_request_id:
                continue
            return dict(chat)
        return None

    def update_chat(self, chat_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        for field in ["name", "profile", "ro_mounts", "rw_mounts", "env_vars", "agent_args", "agent_type"]:
            if field not in patch:
                continue
            if field == "agent_type":
                chat[field] = _normalize_chat_agent_type(patch[field], strict=True)
                continue
            chat[field] = patch[field]

        chat["updated_at"] = _iso_now()
        state["chats"][chat_id] = chat
        self.save(state)
        return chat

    def delete_chat(self, chat_id: str, state: dict[str, Any] | None = None) -> None:
        local_state = state or self.load()
        chat = local_state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        pid = chat.get("pid")
        if isinstance(pid, int):
            stop_requested_at = _iso_now()
            chat["stop_requested_at"] = stop_requested_at
            chat["status_reason"] = CHAT_STATUS_REASON_USER_CLOSED_TAB
            chat["updated_at"] = stop_requested_at
            local_state["chats"][chat_id] = chat
            self.save(local_state, reason=CHAT_STATUS_REASON_USER_CLOSED_TAB)
            _stop_process(pid)
        self._close_runtime(chat_id)

        workspace = Path(str(chat.get("workspace") or self.chat_dir / chat_id))
        if workspace.exists():
            self._delete_path(workspace)
        chat_artifact_storage = self._chat_artifact_storage_root(chat_id)
        if chat_artifact_storage.exists():
            self._delete_path(chat_artifact_storage)
        runtime_config_file = self._chat_runtime_config_path(chat_id)
        if runtime_config_file.exists():
            try:
                runtime_config_file.unlink()
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Failed to remove chat runtime config: {runtime_config_file}") from exc

        with self._chat_input_lock:
            self._chat_input_buffers.pop(chat_id, None)
            self._chat_input_ansi_carry.pop(chat_id, None)
        with self._chat_title_job_lock:
            self._chat_title_jobs_inflight.discard(chat_id)
            self._chat_title_jobs_pending.discard(chat_id)

        local_state["chats"].pop(chat_id, None)
        if state is None:
            self.save(local_state)
        else:
            state["chats"] = local_state["chats"]

    def _delete_path(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete path {path}: {exc}") from exc

    @staticmethod
    def _queue_put(listener: queue.Queue[str | None], value: str | None) -> None:
        RuntimeDomain.queue_put(listener, value)

    def _pop_runtime(self, chat_id: str) -> ChatRuntime | None:
        return self.runtime_domain._pop_runtime(chat_id)  # type: ignore[return-value]

    def _close_runtime(self, chat_id: str) -> None:
        self.runtime_domain.close_runtime(chat_id)

    def _runtime_for_chat(self, chat_id: str) -> ChatRuntime | None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
        if runtime is None:
            return None
        if _is_process_running(runtime.process.pid):
            return runtime
        self._close_runtime(chat_id)
        return None

    def _broadcast_runtime_output(self, chat_id: str, text: str) -> None:
        self.runtime_domain._broadcast_runtime_output(chat_id, text)

    def _runtime_reader_loop(self, chat_id: str, master_fd: int, log_path: Path) -> None:
        self.runtime_domain._runtime_reader_loop(chat_id, master_fd, log_path)

    def _register_runtime(self, chat_id: str, process: subprocess.Popen, master_fd: int) -> None:
        self.runtime_domain._register_runtime(chat_id, process, master_fd)

    def _spawn_chat_process(self, chat_id: str, cmd: list[str]) -> subprocess.Popen:
        return self.runtime_domain.spawn_chat_process(chat_id, cmd)  # type: ignore[return-value]

    @staticmethod
    def _set_terminal_size(fd: int, cols: int, rows: int) -> None:
        RuntimeDomain._set_terminal_size(fd, cols, rows)

    def _chat_log_history(self, chat_id: str) -> str:
        return self.runtime_domain._chat_log_history(chat_id)

    def attach_terminal(self, chat_id: str) -> tuple[queue.Queue[str | None], str]:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        listener: queue.Queue[str | None] = queue.Queue(maxsize=TERMINAL_QUEUE_MAX)
        with self._runtime_lock:
            active_runtime = self._chat_runtimes.get(chat_id)
            if active_runtime is None:
                raise HTTPException(status_code=409, detail="Chat is not running.")
            active_runtime.listeners.add(listener)
        return listener, self._chat_log_history(chat_id)

    def detach_terminal(self, chat_id: str, listener: queue.Queue[str | None]) -> None:
        with self._runtime_lock:
            runtime = self._chat_runtimes.get(chat_id)
            if runtime is None:
                return
            runtime.listeners.discard(listener)

    def _collect_submitted_prompts_from_input(self, chat_id: str, data: str) -> list[str]:
        # Some terminal modes emit Enter as escape sequences (for example "\x1bOM").
        # Normalize known submit controls before ANSI stripping so we keep submit intent.
        normalized = (
            str(data or "")
            .replace("\x1bOM", "\r")
            .replace("\x1b[13~", "\r")
        )
        if not normalized:
            return []

        submissions: list[str] = []
        with self._chat_input_lock:
            current = str(self._chat_input_buffers.get(chat_id) or "")
            ansi_carry = str(self._chat_input_ansi_carry.get(chat_id) or "")
            sanitized, next_carry = _strip_ansi_stream(ansi_carry, normalized)
            sanitized = sanitized.replace("\x1b", "")
            for char in sanitized:
                if char in {"\r", "\n"}:
                    submitted = _compact_whitespace(current).strip()
                    if submitted:
                        submissions.append(submitted)
                    current = ""
                    continue
                if char in {"\b", "\x7f"}:
                    current = current[:-1]
                    continue
                if char == "\x15":  # Ctrl+U clears the current line.
                    current = ""
                    continue
                if ord(char) < 32:
                    continue
                current += char
                if len(current) > 2000:
                    current = current[-2000:]
            self._chat_input_buffers[chat_id] = current
            self._chat_input_ansi_carry[chat_id] = next_carry
        return submissions

    def _record_submitted_prompt(self, chat_id: str, prompt: Any) -> bool:
        submitted = _sanitize_submitted_prompt(prompt)
        if not submitted:
            LOGGER.debug("Title prompt ignored for chat=%s: empty submission.", chat_id)
            return False
        if _looks_like_terminal_control_payload(submitted):
            LOGGER.debug("Title prompt ignored for chat=%s: terminal control payload.", chat_id)
            return False

        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            LOGGER.debug("Title prompt ignored for chat=%s: chat not found.", chat_id)
            return False

        history_raw = chat.get("title_user_prompts")
        history: list[str] = []
        if isinstance(history_raw, list):
            history = [str(item) for item in history_raw if str(item).strip()]

        artifacts = _normalize_chat_artifacts(chat.get("artifacts"))
        current_ids_raw = chat.get("artifact_current_ids")
        if isinstance(current_ids_raw, list):
            current_ids = _normalize_chat_current_artifact_ids(current_ids_raw, artifacts)
        else:
            current_ids = [str(artifact.get("id") or "") for artifact in artifacts if str(artifact.get("id") or "")]
        artifact_map = {str(artifact.get("id") or ""): artifact for artifact in artifacts}
        current_artifacts = [dict(artifact_map[artifact_id]) for artifact_id in current_ids if artifact_id in artifact_map]
        if current_artifacts:
            source_prompt = _sanitize_submitted_prompt(history[-1]) if history else ""
            if not source_prompt:
                source_prompt = "Earlier prompt"
            if len(source_prompt) > CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS:
                source_prompt = source_prompt[:CHAT_ARTIFACT_PROMPT_LABEL_MAX_CHARS].rstrip()
            artifact_prompt_history = _normalize_chat_artifact_prompt_history(chat.get("artifact_prompt_history"))
            archive_time = _iso_now()
            artifact_prompt_history.append(
                {
                    "prompt": source_prompt,
                    "archived_at": archive_time,
                    "artifacts": current_artifacts,
                }
            )
            if len(artifact_prompt_history) > CHAT_ARTIFACT_PROMPT_HISTORY_MAX_ITEMS:
                artifact_prompt_history = artifact_prompt_history[-CHAT_ARTIFACT_PROMPT_HISTORY_MAX_ITEMS:]
            chat["artifact_prompt_history"] = artifact_prompt_history
        else:
            chat["artifact_prompt_history"] = _normalize_chat_artifact_prompt_history(chat.get("artifact_prompt_history"))
        chat["artifact_current_ids"] = []

        if history and _compact_whitespace(str(history[-1])).strip() == submitted:
            chat["updated_at"] = _iso_now()
            state["chats"][chat_id] = chat
            self.save(state, reason="title_prompt_recorded")
            LOGGER.debug("Title prompt duplicate for chat=%s; preserved title state and archived current artifacts.", chat_id)
            return False

        history.append(submitted)

        now = _iso_now()
        chat["title_user_prompts"] = history
        chat["title_user_prompts_updated_at"] = now
        chat["title_status"] = "pending"
        chat["title_error"] = ""
        chat["updated_at"] = now
        state["chats"][chat_id] = chat
        self.save(state, reason="title_prompt_recorded")
        LOGGER.debug("Title prompt recorded for chat=%s prompts=%d", chat_id, len(history))
        self._schedule_chat_title_generation(chat_id)
        return True

    def submit_chat_input_buffer(self, chat_id: str) -> None:
        with self._chat_input_lock:
            buffered = _compact_whitespace(str(self._chat_input_buffers.get(chat_id) or "")).strip()
            self._chat_input_buffers[chat_id] = ""
            self._chat_input_ansi_carry[chat_id] = ""
        if not buffered:
            LOGGER.debug("Buffered terminal input submit ignored for chat=%s: buffer empty.", chat_id)
            return
        LOGGER.debug("Submitting buffered terminal input for chat=%s.", chat_id)
        self._record_submitted_prompt(chat_id, buffered)

    def record_chat_title_prompt(self, chat_id: str, prompt: Any) -> dict[str, Any]:
        state = self.load()
        if chat_id not in state["chats"]:
            raise HTTPException(status_code=404, detail="Chat not found.")
        LOGGER.debug("Direct title prompt submission for chat=%s.", chat_id)
        recorded = self._record_submitted_prompt(chat_id, prompt)
        return {"chat_id": chat_id, "recorded": recorded}

    def _schedule_chat_title_generation(self, chat_id: str) -> None:
        with self._chat_title_job_lock:
            if chat_id in self._chat_title_jobs_inflight:
                self._chat_title_jobs_pending.add(chat_id)
                LOGGER.debug("Title generation already inflight for chat=%s, queued follow-up run.", chat_id)
                return
            self._chat_title_jobs_inflight.add(chat_id)
        LOGGER.debug("Scheduling title generation for chat=%s.", chat_id)

        thread = Thread(target=self._chat_title_generation_loop, args=(chat_id,), daemon=True)
        thread.start()

    def _chat_title_generation_loop(self, chat_id: str) -> None:
        LOGGER.debug("Title generation loop started for chat=%s.", chat_id)
        try:
            while True:
                self._generate_and_store_chat_title(chat_id)
                with self._chat_title_job_lock:
                    if chat_id in self._chat_title_jobs_pending:
                        self._chat_title_jobs_pending.discard(chat_id)
                        LOGGER.debug("Title generation loop continuing for chat=%s (pending rerun).", chat_id)
                        continue
                    self._chat_title_jobs_inflight.discard(chat_id)
                    break
        finally:
            with self._chat_title_job_lock:
                self._chat_title_jobs_inflight.discard(chat_id)
                self._chat_title_jobs_pending.discard(chat_id)
        LOGGER.debug("Title generation loop finished for chat=%s.", chat_id)

    def _generate_and_store_chat_title(self, chat_id: str) -> None:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            LOGGER.debug("Title generation skipped for chat=%s: chat missing.", chat_id)
            return

        history_raw = chat.get("title_user_prompts")
        if not isinstance(history_raw, list):
            LOGGER.debug("Title generation skipped for chat=%s: title history missing.", chat_id)
            return
        history = [str(item) for item in history_raw if str(item).strip()]
        prompts = _normalize_chat_prompt_history(history)
        if not prompts:
            LOGGER.debug("Title generation skipped for chat=%s: no normalized prompts.", chat_id)
            return

        prompt_fingerprint = _chat_title_prompt_fingerprint(prompts, max_chars=CHAT_TITLE_MAX_CHARS)
        cached_fingerprint = str(chat.get("title_prompt_fingerprint") or "")
        cached_title = _truncate_title(str(chat.get("title_cached") or ""), CHAT_TITLE_MAX_CHARS)
        if cached_title and prompt_fingerprint and cached_fingerprint == prompt_fingerprint:
            LOGGER.debug(
                "Title generation skipped for chat=%s: fingerprint unchanged (%s).",
                chat_id,
                prompt_fingerprint[:12],
            )
            return

        auth_mode, api_key = self._chat_title_generation_auth()
        LOGGER.debug(
            "Title generation started for chat=%s prompts=%d auth_mode=%s fingerprint=%s",
            chat_id,
            len(prompts),
            auth_mode,
            prompt_fingerprint[:12],
        )
        if auth_mode == CHAT_TITLE_AUTH_MODE_NONE:
            chat["title_status"] = "error"
            chat["title_error"] = CHAT_TITLE_NO_CREDENTIALS_ERROR
            chat["title_prompt_fingerprint"] = prompt_fingerprint
            chat["title_source"] = "openai"
            chat["title_updated_at"] = _iso_now()
            state["chats"][chat_id] = chat
            self.save(state, reason="title_generation_missing_credentials")
            LOGGER.debug("Title generation failed for chat=%s: no credentials.", chat_id)
            return

        try:
            resolved_title, _ = self._generate_chat_title_with_resolved_auth(
                auth_mode=auth_mode,
                api_key=api_key,
                user_prompts=prompts,
            )
        except Exception as exc:
            chat["title_status"] = "error"
            chat["title_error"] = str(exc)
            chat["title_prompt_fingerprint"] = prompt_fingerprint
            chat["title_source"] = "openai"
            chat["title_updated_at"] = _iso_now()
            state["chats"][chat_id] = chat
            self.save(state, reason="title_generation_error")
            LOGGER.warning("Title generation failed for chat=%s: %s", chat_id, exc)
            return

        chat["title_cached"] = resolved_title
        chat["title_prompt_fingerprint"] = prompt_fingerprint
        chat["title_source"] = "openai"
        chat["title_status"] = "ready"
        chat["title_error"] = ""
        chat["title_updated_at"] = _iso_now()
        state["chats"][chat_id] = chat
        self.save(state, reason="title_generation_ready")
        LOGGER.debug("Title generation succeeded for chat=%s.", chat_id)

    def write_terminal_input(self, chat_id: str, data: str) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        if not data:
            return
        try:
            os.write(runtime.master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as exc:
            raise HTTPException(status_code=409, detail="Failed to write to chat terminal.") from exc
        submissions = self._collect_submitted_prompts_from_input(chat_id, data)
        for prompt in submissions:
            self._record_submitted_prompt(chat_id, prompt)

    def resize_terminal(self, chat_id: str, cols: int, rows: int) -> None:
        runtime = self._runtime_for_chat(chat_id)
        if runtime is None:
            raise HTTPException(status_code=409, detail="Chat is not running.")
        try:
            self._set_terminal_size(runtime.master_fd, cols, rows)
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Invalid terminal resize request.") from exc
        _signal_process_group_winch(int(runtime.process.pid))

    def _delete_fs_entry(self, path: Path) -> None:
        if path.is_symlink():
            try:
                path.unlink()
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"Failed to delete symlink {path}: {exc}") from exc
        if not path.exists():
            return
        if path.is_dir():
            self._delete_path(path)
            return
        try:
            path.unlink()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete file {path}: {exc}") from exc

    def _managed_chat_workspace_paths(self, state: dict[str, Any]) -> set[Path]:
        managed_paths: set[Path] = set()
        chat_root = self.chat_dir.resolve()
        chats = state.get("chats")
        if not isinstance(chats, dict):
            return managed_paths

        for chat_id, chat in chats.items():
            if not isinstance(chat, dict):
                continue
            workspace = Path(str(chat.get("workspace") or self.chat_dir / str(chat_id)))
            try:
                resolved_workspace = workspace.resolve()
                resolved_workspace.relative_to(chat_root)
            except (OSError, RuntimeError, ValueError):
                continue
            managed_paths.add(resolved_workspace)
        return managed_paths

    def _managed_chat_artifact_paths(self, state: dict[str, Any]) -> set[Path]:
        managed_paths: set[Path] = set()
        artifacts_root = self.chat_artifacts_dir.resolve()
        chats = state.get("chats")
        if not isinstance(chats, dict):
            return managed_paths

        for chat_id in chats.keys():
            artifact_dir = self._chat_artifact_storage_root(str(chat_id))
            try:
                resolved_artifact_dir = artifact_dir.resolve()
                resolved_artifact_dir.relative_to(artifacts_root)
            except (OSError, RuntimeError, ValueError):
                continue
            managed_paths.add(resolved_artifact_dir)
        return managed_paths

    def _managed_project_workspace_paths(self, state: dict[str, Any]) -> set[Path]:
        managed_paths: set[Path] = set()
        project_root = self.project_dir.resolve()
        projects = state.get("projects")
        if not isinstance(projects, dict):
            return managed_paths

        for project_id in projects.keys():
            workspace = self.project_workdir(str(project_id))
            try:
                resolved_workspace = workspace.resolve()
                resolved_workspace.relative_to(project_root)
            except (OSError, RuntimeError, ValueError):
                continue
            managed_paths.add(resolved_workspace)
        return managed_paths

    def _managed_project_tmp_paths(self, state: dict[str, Any]) -> set[Path]:
        managed_paths: set[Path] = set()
        project_tmp_root = self.runtime_project_tmp_dir.resolve()
        projects = state.get("projects")
        if not isinstance(projects, dict):
            return managed_paths

        for project_id in projects.keys():
            tmp_root = self.runtime_project_tmp_dir / str(project_id)
            try:
                resolved_tmp_root = tmp_root.resolve()
                resolved_tmp_root.relative_to(project_tmp_root)
            except (OSError, RuntimeError, ValueError):
                continue
            managed_paths.add(resolved_tmp_root)
        return managed_paths

    def _managed_project_tmp_children_paths(self, state: dict[str, Any], project_id: str) -> set[Path]:
        managed_paths: set[Path] = set()
        project_tmp_root = (self.runtime_project_tmp_dir / str(project_id)).resolve()
        project_tmp_workspace = self.project_tmp_workdir(project_id)
        try:
            resolved_workspace = project_tmp_workspace.resolve()
            resolved_workspace.relative_to(project_tmp_root)
            managed_paths.add(resolved_workspace)
        except (OSError, RuntimeError, ValueError):
            pass

        chats = state.get("chats")
        if not isinstance(chats, dict):
            return managed_paths
        for chat_id, chat in chats.items():
            if not isinstance(chat, dict):
                continue
            if str(chat.get("project_id") or "") != str(project_id):
                continue
            chat_tmp = self.chat_tmp_workdir(project_id, str(chat_id))
            try:
                resolved_chat_tmp = chat_tmp.resolve()
                resolved_chat_tmp.relative_to(project_tmp_root)
            except (OSError, RuntimeError, ValueError):
                continue
            managed_paths.add(resolved_chat_tmp)
        return managed_paths

    def _remove_orphan_children(self, root_dir: Path, managed_paths: set[Path]) -> int:
        if not root_dir.exists():
            return 0
        removed = 0
        for child in root_dir.iterdir():
            try:
                resolved_child = child.resolve()
            except (OSError, RuntimeError):
                resolved_child = child
            if resolved_child in managed_paths:
                continue
            self._delete_fs_entry(child)
            removed += 1
        return removed

    def _remove_orphan_log_entries(self, state: dict[str, Any]) -> int:
        if not self.log_dir.exists():
            return 0
        expected_log_names: set[str] = set()
        projects = state.get("projects")
        if isinstance(projects, dict):
            for project_id in projects.keys():
                expected_log_names.add(f"project-{project_id}.log")
        chats = state.get("chats")
        if isinstance(chats, dict):
            for chat_id in chats.keys():
                expected_log_names.add(f"{chat_id}.log")

        removed = 0
        for entry in self.log_dir.iterdir():
            if entry.name in expected_log_names and entry.is_file():
                continue
            self._delete_fs_entry(entry)
            removed += 1
        return removed

    def _reconcile_startup_chat_runtime_state(self, state: dict[str, Any]) -> tuple[int, int, bool]:
        chats = state.get("chats")
        if not isinstance(chats, dict):
            return 0, 0, False

        stopped_chat_processes = 0
        reconciled_chats = 0
        changed = False
        for chat_id, chat in chats.items():
            if not isinstance(chat, dict):
                continue
            pid = chat.get("pid")
            has_pid = isinstance(pid, int)
            process_running = bool(has_pid and _is_process_running(pid))
            if process_running and isinstance(pid, int):
                _stop_process(pid)
                stopped_chat_processes += 1

            normalized_status = _normalize_chat_status(chat.get("status"))
            status_requires_failure = normalized_status in {CHAT_STATUS_RUNNING, CHAT_STATUS_STARTING}
            if not has_pid and not status_requires_failure:
                continue

            if status_requires_failure:
                self._transition_chat_status(
                    chat_id,
                    chat,
                    CHAT_STATUS_FAILED,
                    CHAT_STATUS_REASON_STARTUP_RECONCILE_ORPHAN_PROCESS
                    if has_pid
                    else CHAT_STATUS_REASON_STARTUP_RECONCILE_PROCESS_MISSING,
                )
                if not str(chat.get("start_error") or "").strip():
                    chat["start_error"] = (
                        "Recovered from stale chat runtime state during startup."
                        if has_pid
                        else "Chat runtime process was missing during startup reconciliation."
                    )

            if has_pid:
                chat["pid"] = None
                chat["last_exit_code"] = _normalize_optional_int(chat.get("last_exit_code"))
                chat["last_exit_at"] = _iso_now()
            else:
                chat["last_exit_code"] = _normalize_optional_int(chat.get("last_exit_code"))
                if not str(chat.get("last_exit_at") or "").strip():
                    chat["last_exit_at"] = _iso_now()
            chat["artifact_publish_token_hash"] = ""
            chat["artifact_publish_token_issued_at"] = ""
            chat["agent_tools_token_hash"] = ""
            chat["agent_tools_token_issued_at"] = ""
            chat["stop_requested_at"] = ""
            chat["updated_at"] = _iso_now()
            state["chats"][chat_id] = chat
            changed = True
            reconciled_chats += 1
        return stopped_chat_processes, reconciled_chats, changed

    def startup_reconcile(self) -> dict[str, int]:
        state = self.load()
        stopped_chat_processes, reconciled_chats, state_changed = self._reconcile_startup_chat_runtime_state(state)
        if state_changed:
            self.save(state, reason="startup_reconcile")

        removed_orphan_chat_paths = self._remove_orphan_children(
            self.chat_dir,
            self._managed_chat_workspace_paths(state),
        )
        self._remove_orphan_children(
            self.chat_artifacts_dir,
            self._managed_chat_artifact_paths(state),
        )
        removed_orphan_project_paths = self._remove_orphan_children(
            self.project_dir,
            self._managed_project_workspace_paths(state),
        )
        self._remove_orphan_children(
            self.runtime_project_tmp_dir,
            self._managed_project_tmp_paths(state),
        )
        projects = state.get("projects")
        if isinstance(projects, dict):
            for project_id in projects.keys():
                self._remove_orphan_children(
                    self.runtime_project_tmp_dir / str(project_id),
                    self._managed_project_tmp_children_paths(state, str(project_id)),
                )
        removed_orphan_log_entries = self._remove_orphan_log_entries(state)
        removed_stale_docker_containers = _docker_remove_stale_containers(STARTUP_STALE_DOCKER_CONTAINER_PREFIXES)

        return {
            "stopped_chat_processes": stopped_chat_processes,
            "reconciled_chats": reconciled_chats,
            "removed_orphan_chat_paths": removed_orphan_chat_paths,
            "removed_orphan_project_paths": removed_orphan_project_paths,
            "removed_orphan_log_entries": removed_orphan_log_entries,
            "removed_stale_docker_containers": removed_stale_docker_containers,
        }

    def _startup_reconcile_worker(self) -> None:
        summary = self.startup_reconcile()
        LOGGER.info(
            "Startup reconciliation completed: "
            "stopped_chat_processes=%d reconciled_chats=%d "
            "removed_orphan_chat_paths=%d removed_orphan_project_paths=%d "
            "removed_orphan_log_entries=%d removed_stale_docker_containers=%d",
            summary["stopped_chat_processes"],
            summary["reconciled_chats"],
            summary["removed_orphan_chat_paths"],
            summary["removed_orphan_project_paths"],
            summary["removed_orphan_log_entries"],
            summary["removed_stale_docker_containers"],
        )

    def schedule_startup_reconcile(self) -> None:
        with self._startup_reconcile_lock:
            if self._startup_reconcile_scheduled:
                return
            self._startup_reconcile_scheduled = True
            worker = Thread(target=self._startup_reconcile_worker, daemon=True, name="agent-hub-startup-reconcile")
            self._startup_reconcile_thread = worker
            worker.start()

    def clean_start(self) -> dict[str, int]:
        self.cancel_openai_account_login()
        state = self.load()

        runtime_ids = self.runtime_domain.runtime_ids()
        for chat_id in runtime_ids:
            self._close_runtime(chat_id)

        stopped_chats = 0
        image_tags: set[str] = set()
        for chat in state["chats"].values():
            pid = chat.get("pid")
            if isinstance(pid, int) and _is_process_running(pid):
                _stop_process(pid)
                stopped_chats += 1
            snapshot_tag = str(chat.get("setup_snapshot_image") or "").strip()
            if snapshot_tag:
                image_tags.add(snapshot_tag)

        projects_reset = 0
        for project in state["projects"].values():
            snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
            if snapshot_tag:
                image_tags.add(snapshot_tag)
            if project.get("setup_snapshot_image"):
                projects_reset += 1
            project["setup_snapshot_image"] = ""
            project.pop("snapshot_updated_at", None)
            project["build_status"] = "pending"
            project["build_error"] = ""
            project["build_started_at"] = ""
            project["build_finished_at"] = ""
            project["updated_at"] = _iso_now()

        cleared_chats = len(state["chats"])
        state["chats"] = {}

        for path in [self.chat_dir, self.project_dir, self.log_dir, self.runtime_tmp_dir, self.artifacts_dir]:
            if path.exists():
                self._delete_path(path)
            path.mkdir(parents=True, exist_ok=True)
        self.runtime_project_tmp_dir.mkdir(parents=True, exist_ok=True)
        self.chat_artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.session_artifacts_dir.mkdir(parents=True, exist_ok=True)

        self.save(state)
        _docker_remove_images(("agent-hub-setup-", "agent-base-"), image_tags)

        return {
            "stopped_chats": stopped_chats,
            "cleared_chats": cleared_chats,
            "projects_reset": projects_reset,
            "docker_images_requested": len(image_tags),
        }

    def shutdown(self) -> dict[str, int]:
        self.cancel_openai_account_login()
        runtime_ids = self.runtime_domain.runtime_ids()
        for chat_id in runtime_ids:
            self._close_runtime(chat_id)

        state = self.load()
        running_chat_ids: list[str] = []
        running_pids: list[int] = []
        for chat_id, chat in state["chats"].items():
            pid = chat.get("pid")
            if isinstance(pid, int) and _is_process_running(pid):
                running_chat_ids.append(chat_id)
                running_pids.append(pid)

        stopped = _stop_processes(running_pids, timeout_seconds=4.0)
        if running_chat_ids:
            for chat_id in running_chat_ids:
                state["chats"].pop(chat_id, None)
            self.save(state)
        return {"stopped_chats": stopped, "closed_chats": len(running_chat_ids)}

    def _ensure_chat_clone(self, chat: dict[str, Any], project: dict[str, Any]) -> Path:
        workspace = Path(str(chat.get("workspace") or self.chat_dir / chat["id"]))
        if workspace.exists():
            git_dir = workspace / ".git"
            if git_dir.is_dir():
                return workspace
            self._delete_path(workspace)

            workspace = Path(str(chat.get("workspace") or self.chat_dir / chat["id"]))

        workspace.mkdir(parents=True, exist_ok=True)
        git_env = self._github_git_env_for_repo(
            str(project.get("repo_url") or ""),
            project=project,
            context_key=f"chat_clone:{chat.get('id')}",
        )
        _run(["git", "clone", project["repo_url"], str(workspace)], check=True, env=git_env)
        return workspace

    def _ensure_project_clone(self, project: dict[str, Any]) -> Path:
        workspace = self.project_workdir(project["id"])
        if workspace.exists():
            git_dir = workspace / ".git"
            if git_dir.is_dir():
                return workspace
            self._delete_path(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        git_env = self._github_git_env_for_repo(
            str(project.get("repo_url") or ""),
            project=project,
            context_key=f"project_clone:{project.get('id')}",
        )
        _run(["git", "clone", project["repo_url"], str(workspace)], check=True, env=git_env)
        return workspace

    def _sync_checkout_to_remote(self, workspace: Path, project: dict[str, Any]) -> None:
        git_env = self._github_git_env_for_repo(
            str(project.get("repo_url") or ""),
            project=project,
            context_key=f"project_sync:{project.get('id')}",
        )
        _run_for_repo(["fetch", "--all", "--prune"], workspace, check=True, env=git_env)
        branch = str(project.get("default_branch") or "").strip()
        remote_default = _git_default_remote_branch(workspace)
        if remote_default:
            branch = remote_default

        if not branch:
            raise ConfigError("Unable to determine remote branch for sync: missing project.default_branch and origin/HEAD.")

        if not _git_has_remote_branch(workspace, branch):
            raise ConfigError(f"Unable to determine remote branch for sync: origin/{branch} not found.")

        _run_for_repo(["checkout", branch], workspace, check=True)
        _run_for_repo(["reset", "--hard", f"origin/{branch}"], workspace, check=True)
        _run_for_repo(["clean", "-fd"], workspace, check=True)

    def _resolve_project_base_value(self, workspace: Path, project: dict[str, Any]) -> tuple[str, str] | None:
        base_mode = _normalize_base_image_mode(project.get("base_image_mode"))
        base_value = _normalize_base_image_value(base_mode, project.get("base_image_value"))

        if base_mode == "tag":
            return "base-image", base_value
        if not base_value:
            raise HTTPException(
                status_code=400,
                detail="base_image_value is required when base_image_mode is 'repo_path'.",
            )

        workspace_root = workspace.resolve()
        base_candidate = Path(base_value)
        if base_candidate.is_absolute():
            resolved_base = base_candidate.resolve()
        else:
            resolved_base = (workspace / base_candidate).resolve()
        try:
            resolved_base.relative_to(workspace_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Base path must be inside the checked-out project. "
                    f"Got: {base_value}"
                ),
            ) from exc
        if not resolved_base.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Base path does not exist in project workspace: {base_value}",
            )
        if not (resolved_base.is_file() or resolved_base.is_dir()):
            raise HTTPException(
                status_code=400,
                detail=f"Base path must be a file or directory: {base_value}",
            )
        return "base", str(resolved_base)

    def _append_project_base_args(self, cmd: list[str], workspace: Path, project: dict[str, Any]) -> None:
        resolved = self._resolve_project_base_value(workspace, project)
        if not resolved:
            return
        flag, value = resolved
        if flag == "base":
            base_path = Path(value)
            if base_path.is_file():
                # Dockerfiles stored under subdirectories commonly still need the repository
                # root as build context for COPY paths (for example COPY src ./src).
                cmd.extend(["--base-docker-context", str(workspace.resolve())])
                cmd.extend(["--base-dockerfile", str(base_path)])
                return
        cmd.extend([f"--{flag}", value])

    def _project_setup_snapshot_tag(self, project: dict[str, Any]) -> str:
        project_id = str(project.get("id") or "")[:12] or "project"
        normalized_base_mode = _normalize_base_image_mode(project.get("base_image_mode"))
        normalized_base_value = _normalize_base_image_value(
            normalized_base_mode,
            project.get("base_image_value"),
        )
        payload = json.dumps(
            {
                "snapshot_schema_version": _snapshot_schema_version(),
                "project_id": project.get("id"),
                "default_branch": project.get("default_branch") or "",
                "repo_head_sha": project.get("repo_head_sha") or "",
                "setup_script": str(project.get("setup_script") or ""),
                "base_mode": normalized_base_mode,
                "base_value": normalized_base_value,
                "default_ro_mounts": list(project.get("default_ro_mounts") or []),
                "default_rw_mounts": list(project.get("default_rw_mounts") or []),
                "default_env_vars": list(project.get("default_env_vars") or []),
                "agent_cli_runtime_inputs_fingerprint": _agent_cli_runtime_inputs_fingerprint(),
            },
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return f"agent-hub-setup-{project_id}-{digest}"

    def _ensure_project_setup_snapshot(
        self,
        workspace: Path,
        project: dict[str, Any],
        log_path: Path | None = None,
        project_id: str | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> str:
        setup_script = str(project.get("setup_script") or "").strip()
        snapshot_tag = self._project_setup_snapshot_tag(project)
        resolved_project_id = str(project_id or project.get("id") or "").strip()
        if _docker_image_exists(snapshot_tag):
            if log_path is not None:
                line = f"Using cached setup snapshot image '{snapshot_tag}'\n"
                with log_path.open("a", encoding="utf-8", errors="ignore") as log_file:
                    log_file.write(line)
                if resolved_project_id:
                    self._emit_project_build_log(resolved_project_id, line)
                if on_output is not None:
                    on_output(line)
            return snapshot_tag

        repo_url = str(project.get("repo_url") or "")
        project_tmp_workspace = self.project_tmp_workdir(resolved_project_id or str(project.get("id") or ""))
        project_tmp_workspace.mkdir(parents=True, exist_ok=True)
        cmd = self._prepare_agent_cli_command(
            workspace=workspace,
            container_project_name=_container_project_name(project.get("name") or project.get("id")),
            runtime_config_file=self.config_file,
            agent_type=DEFAULT_CHAT_AGENT_TYPE,
            run_mode=self._runtime_run_mode(),
            agent_tools_url=f"{self.artifact_publish_base_url}/api/projects/{resolved_project_id}/agent-tools",
            agent_tools_token="snapshot-token",
            agent_tools_project_id=resolved_project_id,
            repo_url=repo_url,
            project=project,
            snapshot_tag=snapshot_tag,
            ro_mounts=project.get("default_ro_mounts"),
            rw_mounts=project.get("default_rw_mounts"),
            env_vars=project.get("default_env_vars"),
            setup_script=setup_script,
            prepare_snapshot_only=True,
            project_in_image=True,
            runtime_tmp_mount=str(project_tmp_workspace),
            context_key=f"snapshot:{project.get('id')}",
        )
        if log_path is None:
            _run(cmd, check=True)
        else:
            emit_build_output: Callable[[str], None] | None = None
            if resolved_project_id or on_output is not None:

                def emit_build_output(chunk: str) -> None:
                    if resolved_project_id:
                        self._emit_project_build_log(resolved_project_id, chunk)
                    if on_output is not None:
                        on_output(chunk)

            on_process_start: Callable[[subprocess.Popen[str]], None] | None = None
            if resolved_project_id:

                def on_process_start(process: subprocess.Popen[str]) -> None:
                    self._set_project_build_request_process(resolved_project_id, process)

            try:
                _run_logged(
                    cmd,
                    log_path=log_path,
                    check=True,
                    on_output=emit_build_output,
                    on_process_start=on_process_start,
                )
            finally:
                if resolved_project_id:
                    self._set_project_build_request_process(resolved_project_id, None)
        return snapshot_tag

    def _prepare_project_snapshot_for_project(
        self,
        project: dict[str, Any],
        log_path: Path | None = None,
    ) -> str:
        project_id = str(project.get("id") or "")
        if project_id and self._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=PROJECT_BUILD_CANCELLED_ERROR)
        workspace = self._ensure_project_clone(project)
        if project_id and self._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=PROJECT_BUILD_CANCELLED_ERROR)
        self._sync_checkout_to_remote(workspace, project)
        if project_id and self._is_project_build_cancelled(project_id):
            raise HTTPException(status_code=409, detail=PROJECT_BUILD_CANCELLED_ERROR)
        head_result = _run_for_repo(["rev-parse", "HEAD"], workspace, capture=True)
        project["repo_head_sha"] = head_result.stdout.strip()
        return self._ensure_project_setup_snapshot(
            workspace,
            project,
            log_path=log_path,
            project_id=str(project.get("id") or ""),
        )

    def _chat_container_outdated_state(
        self,
        *,
        chat: dict[str, Any],
        project: dict[str, Any],
        is_running: bool,
    ) -> tuple[bool, str]:
        if not is_running or not isinstance(project, dict):
            return False, ""

        latest_snapshot = str(project.get("setup_snapshot_image") or "").strip()
        expected_snapshot = self._project_setup_snapshot_tag(project)
        build_status = str(project.get("build_status") or "").strip().lower()
        if build_status != "ready" or not latest_snapshot or latest_snapshot != expected_snapshot:
            return False, ""

        active_snapshot = str(chat.get("setup_snapshot_image") or "").strip()
        if not active_snapshot or active_snapshot == latest_snapshot:
            return False, ""

        reason = (
            f"Running on setup snapshot '{active_snapshot}' while project is ready on '{latest_snapshot}'. "
            "Refresh to restart on the latest container and resume chat context."
        )
        return True, reason

    @staticmethod
    def _resume_agent_args(agent_type: str, agent_args: list[str]) -> list[str]:
        normalized_args = [str(arg) for arg in agent_args if str(arg).strip()]
        if agent_type == AGENT_TYPE_CLAUDE:
            if _has_cli_option(normalized_args, long_option="--continue") or _has_cli_option(
                normalized_args, long_option="--resume"
            ):
                return normalized_args
        if agent_type == AGENT_TYPE_GEMINI:
            if _has_cli_option(normalized_args, long_option="--resume", short_option="-r"):
                return normalized_args

        resume_args = list(AGENT_RESUME_ARGS_BY_TYPE.get(agent_type, ()))
        if not resume_args:
            return normalized_args
        return [*resume_args, *normalized_args]

    def state_payload(self) -> dict[str, Any]:
        state = self.load()
        project_map: dict[str, dict[str, Any]] = {}
        should_save = False
        for pid, project in state["projects"].items():
            project_copy = dict(project)
            normalized_base_mode = _normalize_base_image_mode(project_copy.get("base_image_mode"))
            normalized_base_value = _normalize_base_image_value(
                normalized_base_mode,
                project_copy.get("base_image_value"),
            )
            project_copy["base_image_mode"] = normalized_base_mode
            project_copy["base_image_value"] = normalized_base_value
            project_copy["default_ro_mounts"] = list(project_copy.get("default_ro_mounts") or [])
            project_copy["default_rw_mounts"] = list(project_copy.get("default_rw_mounts") or [])
            project_copy["default_env_vars"] = list(project_copy.get("default_env_vars") or [])
            project_copy["setup_snapshot_image"] = str(project_copy.get("setup_snapshot_image") or "")
            project_copy["build_status"] = str(project_copy.get("build_status") or "pending")
            project_copy["build_error"] = str(project_copy.get("build_error") or "")
            project_copy["build_started_at"] = str(project_copy.get("build_started_at") or "")
            project_copy["build_finished_at"] = str(project_copy.get("build_finished_at") or "")
            normalized_binding = _normalize_project_credential_binding(project_copy.get("credential_binding"))
            project_copy["credential_binding"] = normalized_binding
            if state["projects"].get(pid, {}).get("base_image_mode") != normalized_base_mode:
                state["projects"][pid]["base_image_mode"] = normalized_base_mode
                should_save = True
            if str(state["projects"].get(pid, {}).get("base_image_value") or "").strip() != normalized_base_value:
                state["projects"][pid]["base_image_value"] = normalized_base_value
                should_save = True
            if state["projects"].get(pid, {}).get("credential_binding") != normalized_binding:
                state["projects"][pid]["credential_binding"] = normalized_binding
                should_save = True
            log_path = self.project_build_log(pid)
            try:
                project_copy["has_build_log"] = log_path.exists() and log_path.stat().st_size > 0
            except OSError:
                project_copy["has_build_log"] = False
            project_map[pid] = project_copy
        chats = []
        for chat_id, chat in list(state["chats"].items()):
            chat_copy = dict(chat)
            pid = chat_copy.get("pid")
            chat_copy["ro_mounts"] = list(chat_copy.get("ro_mounts") or [])
            chat_copy["rw_mounts"] = list(chat_copy.get("rw_mounts") or [])
            chat_copy["env_vars"] = list(chat_copy.get("env_vars") or [])
            chat_copy["agent_type"] = _normalize_state_chat_agent_type(
                chat_copy.get("agent_type"),
                chat_id=str(chat_id),
            )
            chat_copy["setup_snapshot_image"] = str(chat_copy.get("setup_snapshot_image") or "")
            cleaned_artifacts = _normalize_chat_artifacts(chat_copy.get("artifacts"))
            if chat_id in state["chats"] and cleaned_artifacts != _normalize_chat_artifacts(state["chats"][chat_id].get("artifacts")):
                state["chats"][chat_id]["artifacts"] = cleaned_artifacts
                should_save = True
            current_ids_raw = chat_copy.get("artifact_current_ids")
            if isinstance(current_ids_raw, list):
                cleaned_current_artifact_ids = _normalize_chat_current_artifact_ids(current_ids_raw, cleaned_artifacts)
            else:
                cleaned_current_artifact_ids = [
                    str(artifact.get("id") or "")
                    for artifact in cleaned_artifacts
                    if str(artifact.get("id") or "")
                ]
            if chat_id in state["chats"]:
                state_current_ids_raw = state["chats"][chat_id].get("artifact_current_ids")
                if isinstance(state_current_ids_raw, list):
                    state_current_artifact_ids = _normalize_chat_current_artifact_ids(state_current_ids_raw, cleaned_artifacts)
                else:
                    state_current_artifact_ids = [
                        str(artifact.get("id") or "")
                        for artifact in cleaned_artifacts
                        if str(artifact.get("id") or "")
                    ]
                if cleaned_current_artifact_ids != state_current_artifact_ids:
                    state["chats"][chat_id]["artifact_current_ids"] = cleaned_current_artifact_ids
                    should_save = True
            cleaned_artifact_prompt_history = _normalize_chat_artifact_prompt_history(chat_copy.get("artifact_prompt_history"))
            if chat_id in state["chats"] and cleaned_artifact_prompt_history != _normalize_chat_artifact_prompt_history(
                state["chats"][chat_id].get("artifact_prompt_history")
            ):
                state["chats"][chat_id]["artifact_prompt_history"] = cleaned_artifact_prompt_history
                should_save = True
            project_for_chat = project_map.get(chat_copy["project_id"], {})
            project_name = str(project_for_chat.get("name") or chat_copy["project_id"] or "project")
            chat_copy["artifacts"] = [self._chat_artifact_public_payload(chat_id, artifact) for artifact in reversed(cleaned_artifacts)]
            chat_copy["artifact_current_ids"] = cleaned_current_artifact_ids
            chat_copy["artifact_prompt_history"] = [
                self._chat_artifact_history_public_payload(chat_id, entry)
                for entry in reversed(cleaned_artifact_prompt_history)
            ]
            chat_copy["ready_ack_guid"] = str(chat_copy.get("ready_ack_guid") or "").strip()
            chat_copy["ready_ack_stage"] = _normalize_ready_ack_stage(chat_copy.get("ready_ack_stage"))
            chat_copy["ready_ack_at"] = str(chat_copy.get("ready_ack_at") or "")
            ready_ack_meta = chat_copy.get("ready_ack_meta")
            chat_copy["ready_ack_meta"] = ready_ack_meta if isinstance(ready_ack_meta, dict) else {}
            chat_copy.pop("artifact_publish_token_hash", None)
            chat_copy.pop("artifact_publish_token_issued_at", None)
            chat_copy.pop("agent_tools_token_hash", None)
            chat_copy.pop("agent_tools_token_issued_at", None)
            chat_copy["create_request_id"] = _compact_whitespace(str(chat_copy.get("create_request_id") or "")).strip()
            running = _is_process_running(pid)
            normalized_status = _normalize_chat_status(chat_copy.get("status"))
            if running:
                if normalized_status != CHAT_STATUS_RUNNING and chat_id in state["chats"]:
                    self._transition_chat_status(
                        chat_id,
                        state["chats"][chat_id],
                        CHAT_STATUS_RUNNING,
                        "chat_process_running_during_state_refresh",
                    )
                    should_save = True
                    persisted_chat = state["chats"][chat_id]
                    chat_copy["status"] = persisted_chat.get("status")
                    chat_copy["status_reason"] = persisted_chat.get("status_reason")
                    chat_copy["last_status_transition_at"] = persisted_chat.get("last_status_transition_at")
                    chat_copy["updated_at"] = persisted_chat.get("updated_at")
                chat_copy["status"] = CHAT_STATUS_RUNNING
            else:
                self._close_runtime(chat_id)
                was_running = normalized_status in {CHAT_STATUS_RUNNING, CHAT_STATUS_STARTING} or isinstance(pid, int)
                if was_running and chat_id in state["chats"]:
                    persisted_chat = state["chats"][chat_id]
                    self._transition_chat_status(
                        chat_id,
                        persisted_chat,
                        CHAT_STATUS_FAILED,
                        "chat_process_not_running_during_state_refresh",
                    )
                    if not str(persisted_chat.get("start_error") or "").strip():
                        persisted_chat["start_error"] = "Chat process exited unexpectedly."
                    persisted_chat["pid"] = None
                    persisted_chat["artifact_publish_token_hash"] = ""
                    persisted_chat["artifact_publish_token_issued_at"] = ""
                    persisted_chat["agent_tools_token_hash"] = ""
                    persisted_chat["agent_tools_token_issued_at"] = ""
                    persisted_chat["last_exit_code"] = _normalize_optional_int(persisted_chat.get("last_exit_code"))
                    if not str(persisted_chat.get("last_exit_at") or "").strip():
                        persisted_chat["last_exit_at"] = _iso_now()
                    persisted_chat["stop_requested_at"] = ""
                    state["chats"][chat_id] = persisted_chat
                    chat_copy["status"] = persisted_chat.get("status")
                    chat_copy["status_reason"] = persisted_chat.get("status_reason")
                    chat_copy["last_status_transition_at"] = persisted_chat.get("last_status_transition_at")
                    chat_copy["updated_at"] = persisted_chat.get("updated_at")
                    chat_copy["start_error"] = persisted_chat.get("start_error")
                    chat_copy["last_exit_code"] = persisted_chat.get("last_exit_code")
                    chat_copy["last_exit_at"] = persisted_chat.get("last_exit_at")
                    chat_copy["stop_requested_at"] = persisted_chat.get("stop_requested_at")
                    chat_copy["pid"] = None
                    should_save = True
                else:
                    chat_copy["status"] = normalized_status
                    if chat_copy.get("pid") is not None:
                        chat_copy["pid"] = None
                        if chat_id in state["chats"]:
                            state["chats"][chat_id]["pid"] = None
                            state["chats"][chat_id]["updated_at"] = _iso_now()
                            should_save = True
            chat_copy["is_running"] = running
            chat_copy["container_workspace"] = str(chat_copy.get("container_workspace") or "") or _container_workspace_path_for_project(
                project_name
            )
            chat_copy["project_name"] = project_name
            is_outdated, outdated_reason = self._chat_container_outdated_state(
                chat=chat_copy,
                project=project_for_chat,
                is_running=running,
            )
            chat_copy["container_outdated"] = is_outdated
            chat_copy["container_outdated_reason"] = outdated_reason
            subtitle = _chat_subtitle_from_log(self.chat_log(chat_id))
            cached_title = _truncate_title(str(chat_copy.get("title_cached") or ""), CHAT_TITLE_MAX_CHARS)
            if cached_title and _looks_like_terminal_control_payload(cached_title):
                cached_title = ""
                if chat_id in state["chats"]:
                    state["chats"][chat_id]["title_cached"] = ""
                    state["chats"][chat_id]["title_source"] = ""
                    state["chats"][chat_id]["title_prompt_fingerprint"] = ""
                    should_save = True
            history_raw = chat_copy.get("title_user_prompts")
            if isinstance(history_raw, list):
                cleaned_history = [
                    str(item)
                    for item in history_raw
                    if str(item).strip() and not _looks_like_terminal_control_payload(str(item))
                ]
                if chat_id in state["chats"] and cleaned_history != list(history_raw):
                    state["chats"][chat_id]["title_user_prompts"] = cleaned_history
                    should_save = True
            title_status = str(chat_copy.get("title_status") or "idle").lower()
            if title_status == "pending":
                pending_history = chat_copy.get("title_user_prompts")
                if isinstance(pending_history, list):
                    normalized_prompts = _normalize_chat_prompt_history([str(item) for item in pending_history if str(item).strip()])
                    if normalized_prompts:
                        self._schedule_chat_title_generation(chat_id)
            chat_copy["display_name"] = cached_title or _chat_display_name(chat_copy.get("name"))
            title_error = _compact_whitespace(str(chat_copy.get("title_error") or ""))
            if not subtitle and title_error:
                subtitle = _short_summary(f"Title generation error: {title_error}", max_words=20, max_chars=CHAT_SUBTITLE_MAX_CHARS)
            chat_copy["display_subtitle"] = subtitle
            chats.append(chat_copy)

        if should_save:
            self.save(state, reason="state_payload_reconcile")

        state["chats"] = chats
        state["projects"] = list(project_map.values())
        state["settings"] = self.settings_service.settings_payload(state)
        return state

    def start_chat(self, chat_id: str, *, resume: bool = False) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat["project_id"])
        if project is None:
            raise HTTPException(status_code=404, detail="Parent project missing.")

        if _normalize_chat_status(chat.get("status")) == CHAT_STATUS_RUNNING and _is_process_running(chat.get("pid")):
            raise HTTPException(status_code=409, detail="Chat is already running.")

        build_status = str(project.get("build_status") or "")
        snapshot_tag = str(project.get("setup_snapshot_image") or "").strip()
        expected_snapshot_tag = self._project_setup_snapshot_tag(project)
        snapshot_ready = (
            build_status == "ready"
            and snapshot_tag
            and snapshot_tag == expected_snapshot_tag
            and _docker_image_exists(snapshot_tag)
        )
        if not snapshot_ready:
            raise HTTPException(status_code=409, detail="Project image is not ready yet. Wait for setup build to finish.")

        self._transition_chat_status(chat_id, chat, CHAT_STATUS_STARTING, "chat_start_requested")
        chat["start_error"] = ""
        chat["last_exit_code"] = None
        chat["last_exit_at"] = ""
        chat["stop_requested_at"] = ""
        chat["pid"] = None
        state["chats"][chat_id] = chat
        self.save(state, reason="chat_start_requested")

        try:
            workspace = self._ensure_chat_clone(chat, project)
            self._sync_checkout_to_remote(workspace, project)
            with self._chat_input_lock:
                self._chat_input_buffers[chat_id] = ""
                self._chat_input_ansi_carry[chat_id] = ""
            artifact_publish_token = _new_artifact_publish_token()
            agent_tools_token = _new_agent_tools_token()
            ready_ack_guid = _new_ready_ack_guid()
            agent_tools_url = self._chat_agent_tools_url(chat_id)
            agent_tools_project_id = str(project.get("id") or "")
            agent_type = _normalize_chat_agent_type(chat.get("agent_type"), strict=True)
            runtime_config_file = self._prepare_chat_runtime_config(
                chat_id,
                agent_type=agent_type,
                agent_tools_url=agent_tools_url,
                agent_tools_token=agent_tools_token,
                agent_tools_project_id=agent_tools_project_id,
                agent_tools_chat_id=chat_id,
                trusted_project_path=_container_workspace_path_for_project(project.get("name") or project.get("id")),
            )
            chat["agent_type"] = agent_type
            container_workspace = _container_workspace_path_for_project(project.get("name") or project.get("id"))
            chat_tmp_workspace = self.chat_tmp_workdir(agent_tools_project_id, chat_id)
            chat_tmp_workspace.mkdir(parents=True, exist_ok=True)

            agent_args = [str(arg) for arg in (chat.get("agent_args") or []) if str(arg).strip()]
            if resume and agent_type == AGENT_TYPE_CODEX:
                # agent_cli resume mode and explicit args are mutually exclusive.
                agent_args = []
            elif resume:
                agent_args = self._resume_agent_args(agent_type, agent_args)

            cmd = self._prepare_agent_cli_command(
                workspace=workspace,
                container_project_name=_container_project_name(project.get("name") or project.get("id")),
                runtime_config_file=runtime_config_file,
                agent_type=agent_type,
                run_mode=self._runtime_run_mode(),
                agent_tools_url=agent_tools_url,
                agent_tools_token=agent_tools_token,
                agent_tools_project_id=agent_tools_project_id,
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
                context_key=f"chat_start:{chat_id}",
                extra_args=agent_args,
            )

            state = self.load()
            chat = state["chats"].get(chat_id)
            if chat is None:
                raise HTTPException(status_code=404, detail="Chat was removed before runtime launch.")
            chat["artifact_publish_token_hash"] = _hash_artifact_publish_token(artifact_publish_token)
            chat["artifact_publish_token_issued_at"] = _iso_now()
            chat["agent_tools_token_hash"] = _hash_agent_tools_token(agent_tools_token)
            chat["agent_tools_token_issued_at"] = _iso_now()
            chat["ready_ack_guid"] = ready_ack_guid
            chat["ready_ack_stage"] = AGENT_READY_ACK_STAGE_CONTAINER_BOOTSTRAPPED
            chat["ready_ack_at"] = ""
            chat["ready_ack_meta"] = {}
            state["chats"][chat_id] = chat
            self.save(state, reason="chat_start_runtime_tokens_issued")

            proc = self._spawn_chat_process(chat_id, cmd)
        except Exception as exc:
            detail = self._chat_start_error_detail(exc)
            LOGGER.warning(
                "Chat failed to start chat_id=%s project_id=%s reason=%s detail=%s",
                chat_id,
                chat.get("project_id"),
                "chat_start_failed",
                detail,
            )
            self._mark_chat_start_failed(chat_id, detail=detail, reason="chat_start_failed")
            raise

        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat was removed before start completion.")
        self._transition_chat_status(chat_id, chat, CHAT_STATUS_RUNNING, "chat_start_succeeded")
        chat["start_error"] = ""
        chat["pid"] = proc.pid
        chat["setup_snapshot_image"] = snapshot_tag or ""
        chat["container_workspace"] = container_workspace
        chat["artifact_publish_token_hash"] = _hash_artifact_publish_token(artifact_publish_token)
        chat["artifact_publish_token_issued_at"] = _iso_now()
        chat["agent_tools_token_hash"] = _hash_agent_tools_token(agent_tools_token)
        chat["agent_tools_token_issued_at"] = _iso_now()
        chat["ready_ack_guid"] = str(chat.get("ready_ack_guid") or ready_ack_guid)
        chat["ready_ack_stage"] = _normalize_ready_ack_stage(chat.get("ready_ack_stage"))
        chat["ready_ack_at"] = str(chat.get("ready_ack_at") or "")
        ready_ack_meta = chat.get("ready_ack_meta")
        chat["ready_ack_meta"] = ready_ack_meta if isinstance(ready_ack_meta, dict) else {}
        chat["last_started_at"] = _iso_now()
        chat["stop_requested_at"] = ""
        state["chats"][chat_id] = chat
        self.save(state, reason="chat_start_succeeded")
        return dict(chat)

    def refresh_chat_container(self, chat_id: str) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")
        project = state["projects"].get(chat["project_id"])
        if project is None:
            raise HTTPException(status_code=404, detail="Parent project missing.")

        running = bool(chat.get("status") == "running" and _is_process_running(chat.get("pid")))
        if not running:
            raise HTTPException(status_code=409, detail="Chat must be running to refresh its container.")

        is_outdated, _reason = self._chat_container_outdated_state(chat=chat, project=project, is_running=running)
        if not is_outdated:
            raise HTTPException(status_code=409, detail="Chat container is already up to date.")

        self.close_chat(chat_id)
        return self.start_chat(chat_id, resume=True)

    def close_chat(self, chat_id: str) -> dict[str, Any]:
        state = self.load()
        chat = state["chats"].get(chat_id)
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found.")

        stop_requested_at = _iso_now()
        chat["stop_requested_at"] = stop_requested_at
        chat["status_reason"] = CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED
        chat["updated_at"] = stop_requested_at
        state["chats"][chat_id] = chat
        self.save(state, reason=CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED)
        pid = chat.get("pid")
        if isinstance(pid, int):
            _stop_process(pid)
        self._close_runtime(chat_id)
        with self._chat_input_lock:
            self._chat_input_buffers.pop(chat_id, None)
            self._chat_input_ansi_carry.pop(chat_id, None)

        self._transition_chat_status(chat_id, chat, CHAT_STATUS_STOPPED, CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED)
        chat["start_error"] = ""
        chat["pid"] = None
        chat["artifact_publish_token_hash"] = ""
        chat["artifact_publish_token_issued_at"] = ""
        chat["agent_tools_token_hash"] = ""
        chat["agent_tools_token_issued_at"] = ""
        chat["last_exit_code"] = None
        chat["last_exit_at"] = _iso_now()
        chat["stop_requested_at"] = ""
        state["chats"][chat_id] = chat
        self.save(state, reason=CHAT_STATUS_REASON_CHAT_CLOSE_REQUESTED)
        return dict(chat)


def _html_page() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light dark" />
  <title>Agent Hub</title>
  <style>
    :root {
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d7dce3;
      --line-strong: #c7ced9;
      --text: #0f1722;
      --muted: #627082;
      --accent: #10a37f;
      --accent-strong: #0f8a6d;
      --header: #0b1017;
      --header-subtitle: #c8d0dc;
      --pill-running: #0f9b65;
      --pill-stopped: #6b7280;
      --shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #0a1018;
        --panel: #111923;
        --line: #2a3848;
        --line-strong: #32465d;
        --text: #e6edf7;
        --muted: #9aa8bb;
        --accent: #19b88e;
        --accent-strong: #16a480;
        --header: #060b11;
        --header-subtitle: #9fb1c6;
        --pill-running: #12b375;
        --pill-stopped: #738197;
        --shadow: 0 10px 24px rgba(0, 0, 0, 0.3);
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      background: var(--bg);
      font-family: "Sohne", "Soehne", "Avenir Next", "Inter", "Segoe UI", sans-serif;
      line-height: 1.45;
    }
    header {
      padding: 1.1rem 1.5rem;
      color: #fff;
      background: var(--header);
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    }
    h1 { margin: 0; font-size: 1.35rem; letter-spacing: -0.02em; font-weight: 650; }
    .subhead { margin-top: 0.2rem; color: var(--header-subtitle); font-size: 0.92rem; }
    main {
      max-width: 1240px;
      margin: 0 auto;
      padding: 1rem;
      display: grid;
      gap: 1rem;
      grid-template-columns: minmax(420px, 1fr) minmax(420px, 1fr);
      align-items: start;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1rem;
      box-shadow: var(--shadow);
    }
    section h2 { margin-top: 0; }
    .grid { display: grid; gap: 0.6rem; }
    input, textarea, button, select {
      width: 100%;
      padding: 0.58rem 0.62rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--text);
      font: inherit;
    }
    input:focus, textarea:focus, select:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(16, 163, 127, 0.18);
    }
    textarea {
      min-height: 84px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
      line-height: 1.35;
    }
    .script-input { min-height: 132px; }
    .row { display: grid; grid-template-columns: 2fr 1fr; gap: 0.6rem; }
    .row.base-row { grid-template-columns: 1fr 2fr; }
    .chat {
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.8rem;
      margin-bottom: 0.85rem;
      background: var(--panel);
    }
    .chat h3 { margin: 0 0 0.4rem 0; }
    .meta { font-size: 0.85rem; color: var(--muted); }
    .pill { padding: 0.12rem 0.5rem; border-radius: 999px; font-size: 0.75rem; color: #fff; background: #607d8b; font-weight: 600; }
    .running { background: var(--pill-running); }
    .stopped { background: var(--pill-stopped); }
    .controls { display: flex; gap: 0.5rem; margin-top: 0.5rem; flex-wrap: wrap; }
    button {
      cursor: pointer;
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      font-weight: 600;
      transition: background 120ms ease, border-color 120ms ease;
    }
    button:hover { background: var(--accent-strong); border-color: var(--accent-strong); }
    .controls button { width: auto; }
    .inline-controls { display: flex; gap: 0.45rem; align-items: center; flex-wrap: wrap; }
    .inline-controls button { width: auto; }
    .widget-list { display: grid; gap: 0.5rem; }
    .widget-row {
      display: grid;
      gap: 0.5rem;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0.5rem;
      background: color-mix(in srgb, var(--panel) 94%, transparent);
    }
    .widget-row.volume { grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) 130px auto; }
    .widget-row.env { grid-template-columns: minmax(140px, 0.8fr) minmax(220px, 1fr) auto; }
    .widget-row button { width: auto; }
    .small { padding: 0.42rem 0.56rem; font-size: 0.85rem; }
    .section-label { font-size: 0.8rem; color: var(--muted); margin-top: 0.2rem; }
    .error-banner {
      display: none;
      margin: 0 1rem;
      padding: 0.6rem 0.75rem;
      border-radius: 8px;
      border: 1px solid #f3b2ad;
      color: #7a1610;
      background: #fff0ef;
      font-size: 0.9rem;
    }
    button.secondary {
      background: transparent;
      color: var(--text);
      border-color: var(--line-strong);
    }
    button.secondary:hover {
      background: rgba(127, 127, 127, 0.08);
      border-color: var(--line-strong);
    }
    button.danger {
      background: #b42318;
      border-color: #b42318;
      color: #fff;
    }
    button.danger:hover {
      background: #9f1f15;
      border-color: #9f1f15;
    }
    .muted { color: var(--muted); }
    @media (max-width: 980px) {
      main { grid-template-columns: 1fr; }
      .row { grid-template-columns: 1fr; }
      .widget-row.volume { grid-template-columns: 1fr; }
      .widget-row.env { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Agent Hub</h1>
    <div class="subhead">Project-level workspaces, one cloned directory per chat</div>
  </header>
  <div id="ui-error" class="error-banner"></div>
  <main>
    <section>
      <h2>Projects</h2>
      <form id="project-form" class="grid" onsubmit="createProject(event)">
        <input id="project-repo" required placeholder="https://github.com/org/repo.git" />
        <div class="muted">SSH repository URLs are not supported yet. Use HTTPS when adding projects.</div>
        <div class="row">
          <input id="project-name" placeholder="Optional project name" />
          <input id="project-branch" placeholder="Default branch (optional, auto-detect)" />
        </div>
        <div class="row base-row">
          <select id="project-base-image-mode" onchange="updateBasePlaceholderForCreate()">
            <option value="tag">Docker image tag</option>
            <option value="repo_path">Repo Dockerfile/path</option>
          </select>
          <input id="project-base-image-value" placeholder="ubuntu:24.04" />
        </div>
        <textarea id="project-setup-script" class="script-input" placeholder="Setup script (one command per line, run in the checked-out project)&#10;example:&#10;uv sync&#10;uv run python -m pip install -e ."></textarea>
        <div class="section-label">Default volumes for new chats</div>
        <div id="project-default-volumes" class="widget-list"></div>
        <div class="inline-controls">
          <button type="button" class="secondary small" onclick="addVolumeRow('project-default-volumes')">Add volume</button>
        </div>
        <div class="section-label">Default environment variables for new chats</div>
        <div id="project-default-env" class="widget-list"></div>
        <div class="inline-controls">
          <button type="button" class="secondary small" onclick="addEnvRow('project-default-env')">Add environment variable</button>
        </div>
        <button type="submit">Add project</button>
      </form>
      <h2 style="margin-top:1rem;">Projects</h2>
      <div id="projects"></div>
    </section>
    <section>
      <h2>Chats</h2>
      <div id="chats"></div>
    </section>
  </main>
  <script>
    const DEFAULT_BASE_IMAGE_TAG = 'ubuntu:24.04';

    async function fetchJson(url, options={}) {
      const response = await fetch(url, Object.assign({ headers: { "Content-Type":"application/json" } }, options));
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed with ${response.status}`);
      }
      if (response.status === 204) return null;
      return response.json();
    }

    async function fetchText(url) {
      const response = await fetch(url);
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Request failed with ${response.status}`);
      }
      return response.text();
    }

    function escapeHtml(value) {
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function normalizeBaseMode(mode) {
      return mode === 'repo_path' ? 'repo_path' : 'tag';
    }

    function baseModeLabel(mode) {
      return mode === 'repo_path' ? 'Repo path' : 'Docker tag';
    }

    function baseInputPlaceholder(mode) {
      if (mode === 'repo_path') {
        return 'Path in repo to Dockerfile or dir (e.g. docker/base or docker/base/Dockerfile)';
      }
      return DEFAULT_BASE_IMAGE_TAG;
    }

    function updateBasePlaceholderForCreate() {
      const mode = normalizeBaseMode(document.getElementById('project-base-image-mode').value);
      const input = document.getElementById('project-base-image-value');
      input.placeholder = baseInputPlaceholder(mode);
    }

    function updateBasePlaceholderForProject(projectId) {
      const mode = normalizeBaseMode(document.getElementById(`base-mode-${projectId}`).value);
      const input = document.getElementById(`base-value-${projectId}`);
      input.placeholder = baseInputPlaceholder(mode);
    }

    function addVolumeRow(listId, mount = null, markDirty = true) {
      const list = document.getElementById(listId);
      if (!list) return;
      if (markDirty) uiDirty = true;
      const mode = mount && mount.mode === 'ro' ? 'ro' : 'rw';
      const host = escapeHtml((mount && mount.host) || '');
      const container = escapeHtml((mount && mount.container) || '');
      const row = document.createElement('div');
      row.className = 'widget-row volume';
      row.innerHTML = `
        <input class="vol-host" placeholder="Local path (e.g. /data/datasets)" value="${host}" />
        <input class="vol-container" placeholder="Container path (e.g. /workspace/data)" value="${container}" />
        <select class="vol-mode">
          <option value="rw" ${mode === 'rw' ? 'selected' : ''}>Read-write</option>
          <option value="ro" ${mode === 'ro' ? 'selected' : ''}>Read-only</option>
        </select>
        <button type="button" class="secondary small" onclick="removeWidgetRow(this)">Remove</button>
      `;
      list.appendChild(row);
    }

    function addEnvRow(listId, envVar = null, markDirty = true) {
      const list = document.getElementById(listId);
      if (!list) return;
      if (markDirty) uiDirty = true;
      const key = escapeHtml((envVar && envVar.key) || '');
      const value = escapeHtml((envVar && envVar.value) || '');
      const row = document.createElement('div');
      row.className = 'widget-row env';
      row.innerHTML = `
        <input class="env-key" placeholder="KEY" value="${key}" />
        <input class="env-value" placeholder="VALUE" value="${value}" />
        <button type="button" class="secondary small" onclick="removeWidgetRow(this)">Remove</button>
      `;
      list.appendChild(row);
    }

    function removeWidgetRow(buttonEl) {
      const row = buttonEl.closest('.widget-row');
      if (row) {
        row.remove();
        uiDirty = true;
      }
    }

    function parseMountEntry(spec, mode) {
      if (typeof spec !== 'string') return null;
      const idx = spec.indexOf(':');
      if (idx <= 0 || idx === spec.length - 1) return null;
      return {
        host: spec.slice(0, idx),
        container: spec.slice(idx + 1),
        mode: mode === 'ro' ? 'ro' : 'rw',
      };
    }

    function seedVolumeRows(listId, roMounts = [], rwMounts = []) {
      const list = document.getElementById(listId);
      if (!list) return;
      list.innerHTML = '';
      const all = [];
      (roMounts || []).forEach((spec) => {
        const parsed = parseMountEntry(spec, 'ro');
        if (parsed) all.push(parsed);
      });
      (rwMounts || []).forEach((spec) => {
        const parsed = parseMountEntry(spec, 'rw');
        if (parsed) all.push(parsed);
      });
      all.forEach((entry) => addVolumeRow(listId, entry, false));
    }

    function splitEnvVar(entry) {
      if (typeof entry !== 'string') return { key: '', value: '' };
      const idx = entry.indexOf('=');
      if (idx < 0) return { key: entry, value: '' };
      return { key: entry.slice(0, idx), value: entry.slice(idx + 1) };
    }

    function seedEnvRows(listId, envVars = []) {
      const list = document.getElementById(listId);
      if (!list) return;
      list.innerHTML = '';
      (envVars || []).forEach((entry) => addEnvRow(listId, splitEnvVar(entry), false));
    }

    function collectMountPayload(listId) {
      const list = document.getElementById(listId);
      const ro = [];
      const rw = [];
      if (!list) return { ro_mounts: ro, rw_mounts: rw };

      list.querySelectorAll('.widget-row.volume').forEach((row) => {
        const hostEl = row.querySelector('.vol-host');
        const containerEl = row.querySelector('.vol-container');
        const modeEl = row.querySelector('.vol-mode');
        const host = (hostEl ? hostEl.value : '').trim();
        const container = (containerEl ? containerEl.value : '').trim();
        const mode = modeEl && modeEl.value === 'ro' ? 'ro' : 'rw';
        if (!host && !container) return;
        if (!host || !container) {
          throw new Error('Each volume needs both local and container path.');
        }
        const entry = `${host}:${container}`;
        if (mode === 'ro') ro.push(entry);
        else rw.push(entry);
      });

      return { ro_mounts: ro, rw_mounts: rw };
    }

    function collectEnvPayload(listId) {
      const list = document.getElementById(listId);
      const envVars = [];
      if (!list) return envVars;

      list.querySelectorAll('.widget-row.env').forEach((row) => {
        const keyEl = row.querySelector('.env-key');
        const valueEl = row.querySelector('.env-value');
        const key = (keyEl ? keyEl.value : '').trim();
        const value = valueEl ? valueEl.value : '';
        if (!key && !value) return;
        if (!key) {
          throw new Error('Environment variable key is required when value is provided.');
        }
        envVars.push(`${key}=${value}`);
      });

      return envVars;
    }

    function isEditingFormField() {
      const active = document.activeElement;
      if (!active) return false;
      const tag = (active.tagName || '').toLowerCase();
      return tag === 'input' || tag === 'textarea' || tag === 'select';
    }

    let hasRenderedOnce = false;
    let uiDirty = false;

    document.addEventListener('input', (event) => {
      if (event.target && event.target.closest('.widget-list')) {
        uiDirty = true;
      }
    });

    async function refresh() {
      if (hasRenderedOnce && (isEditingFormField() || uiDirty)) {
        return;
      }
      const errorEl = document.getElementById('ui-error');
      const projects = document.getElementById('projects');
      const chats = document.getElementById('chats');

      try {
        const state = await fetchJson('/api/state');
        errorEl.style.display = 'none';
        errorEl.textContent = '';

        projects.innerHTML = '';
        chats.innerHTML = '';

        state.projects.forEach(project => {
        const projectName = escapeHtml(project.name || 'Unnamed project');
        const projectId = escapeHtml(project.id || '');
        const projectBranch = escapeHtml(project.default_branch || 'master');
        const projectRepo = escapeHtml(project.repo_url || '');
        const setupScriptRaw = String(project.setup_script || '');
        const setupScript = escapeHtml(setupScriptRaw);
        const setupCommandCount = setupScriptRaw.split('\\n').map(line => line.trim()).filter(Boolean).length;
        const baseMode = normalizeBaseMode(project.base_image_mode);
        const baseValueRaw = String(project.base_image_value || '');
        const baseValue = escapeHtml(baseValueRaw);
        const baseSummary = baseValueRaw
          ? `${baseModeLabel(baseMode)}: ${escapeHtml(baseValueRaw)}`
          : 'Default agent_cli base image';
        const defaultVolumeCount = (project.default_ro_mounts || []).length + (project.default_rw_mounts || []).length;
        const defaultEnvCount = (project.default_env_vars || []).length;

        const card = document.createElement('div');
        card.className = 'chat';
        card.innerHTML = `
          <h3>${projectName}</h3>
          <div class="meta">ID: ${projectId}</div>
          <div class="meta">Branch: ${projectBranch}</div>
          <div class="meta">Setup commands: ${setupCommandCount}</div>
          <div class="meta">Base image source: ${baseSummary}</div>
          <div class="meta">Default volumes: ${defaultVolumeCount} | Default env vars: ${defaultEnvCount}</div>
          <div class="grid" style="margin-top:0.5rem;">
            <input value="${projectRepo}" placeholder="Repo URL" id="repo-${project.id}" disabled />
            <div class="row">
              <input id="profile-${project.id}" placeholder="Profile (e.g. fast)" />
              <button onclick="createChatForProject('${project.id}')">Start new chat</button>
            </div>
            <div class="row base-row">
              <select id="base-mode-${project.id}" onchange="updateBasePlaceholderForProject('${project.id}')">
                <option value="tag" ${baseMode === 'tag' ? 'selected' : ''}>Docker image tag</option>
                <option value="repo_path" ${baseMode === 'repo_path' ? 'selected' : ''}>Repo Dockerfile/path</option>
              </select>
              <input id="base-value-${project.id}" value="${baseValue}" placeholder="${escapeHtml(baseInputPlaceholder(baseMode))}" />
            </div>
            <textarea id="setup-${project.id}" class="script-input" placeholder="One command per line; executed sequentially in workspace">${setupScript}</textarea>
            <button onclick="saveProjectSettings('${project.id}')">Save project settings</button>
            <div class="section-label">Default volumes for new chats</div>
            <div id="new-volumes-${project.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addVolumeRow('new-volumes-${project.id}')">Add volume</button>
            </div>
            <div class="section-label">Default environment variables for new chats</div>
            <div id="new-env-${project.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addEnvRow('new-env-${project.id}')">Add environment variable</button>
            </div>
          </div>
          <div class="controls">
            <button class="danger" onclick="deleteProject('${project.id}')">Delete project</button>
          </div>
        `;
        projects.appendChild(card);
        seedVolumeRows(`new-volumes-${project.id}`, project.default_ro_mounts || [], project.default_rw_mounts || []);
        seedEnvRows(`new-env-${project.id}`, project.default_env_vars || []);
        });

        state.chats.forEach(chat => {
        const chatName = escapeHtml(chat.name || 'Unnamed chat');
        const chatProjectName = escapeHtml(chat.project_name || 'Unknown');
        const chatId = escapeHtml(chat.id || '');
        const chatProfile = escapeHtml(chat.profile || 'default');
        const chatProfileInput = escapeHtml(chat.profile || '');
        const workspace = escapeHtml(chat.workspace || '');
        const containerWorkspace = escapeHtml(chat.container_workspace || 'not started yet');
        const volumeCount = (chat.ro_mounts || []).length + (chat.rw_mounts || []).length;
        const envCount = (chat.env_vars || []).length;
        const card = document.createElement('div');
        card.className = 'chat';
        const pill = chat.is_running ? 'running' : 'stopped';
        card.innerHTML = `
          <h3>${chatName}</h3>
          <div class="meta"><span class="pill ${pill}">${chat.status}</span> ${chatProjectName}</div>
          <div class="meta">Chat ID: ${chatId}</div>
          <div class="meta">Profile: ${chatProfile}</div>
          <div class="meta">Workspace: ${workspace}</div>
          <div class="meta">Container folder: ${containerWorkspace}</div>
          <div class="meta">Volumes: ${volumeCount} | Env vars: ${envCount}</div>
          <div class="grid" style="margin-top:0.5rem;">
            <input id="chat-profile-${chat.id}" value="${chatProfileInput}" placeholder="Profile" />
            <div class="section-label">Volumes</div>
            <div id="chat-volumes-${chat.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addVolumeRow('chat-volumes-${chat.id}')">Add volume</button>
            </div>
            <div class="section-label">Environment variables</div>
            <div id="chat-env-${chat.id}" class="widget-list"></div>
            <div class="inline-controls">
              <button type="button" class="secondary small" onclick="addEnvRow('chat-env-${chat.id}')">Add environment variable</button>
            </div>
          </div>
          <div class="controls">
            <button onclick="updateChat('${chat.id}')">Save config</button>
            ${chat.is_running ? `<button class="secondary" onclick="closeChat('${chat.id}')">Close</button>` : `<button onclick="startChat('${chat.id}')">Start</button>`}
            <button class="danger" onclick="deleteChat('${chat.id}')">Delete</button>
            <button class="secondary" onclick="viewLog('${chat.id}')">View logs</button>
          </div>
          <div id="log-${chat.id}" class="muted" style="white-space: pre-wrap; margin-top:0.5rem;"></div>
        `;
        chats.appendChild(card);
        seedVolumeRows(`chat-volumes-${chat.id}`, chat.ro_mounts || [], chat.rw_mounts || []);
        seedEnvRows(`chat-env-${chat.id}`, chat.env_vars || []);
        });

        hasRenderedOnce = true;
      } catch (err) {
        errorEl.style.display = 'block';
        errorEl.textContent = err && err.message ? err.message : String(err);
      }
    }

    async function createProject(event) {
      event.preventDefault();
      let defaultMounts;
      let defaultEnv;
      try {
        defaultMounts = collectMountPayload('project-default-volumes');
        defaultEnv = collectEnvPayload('project-default-env');
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        repo_url: document.getElementById('project-repo').value,
        name: document.getElementById('project-name').value,
        default_branch: document.getElementById('project-branch').value,
        base_image_mode: document.getElementById('project-base-image-mode').value,
        base_image_value: document.getElementById('project-base-image-value').value,
        setup_script: document.getElementById('project-setup-script').value,
        default_ro_mounts: defaultMounts.ro_mounts,
        default_rw_mounts: defaultMounts.rw_mounts,
        default_env_vars: defaultEnv,
      };
      await fetchJson('/api/projects', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('project-form').reset();
      updateBasePlaceholderForCreate();
      uiDirty = false;
      seedVolumeRows('project-default-volumes', [], []);
      seedEnvRows('project-default-env', []);
      await refresh();
    }

    async function saveProjectSettings(projectId) {
      let defaultMounts;
      let defaultEnv;
      try {
        defaultMounts = collectMountPayload(`new-volumes-${projectId}`);
        defaultEnv = collectEnvPayload(`new-env-${projectId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        base_image_mode: document.getElementById(`base-mode-${projectId}`).value,
        base_image_value: document.getElementById(`base-value-${projectId}`).value,
        setup_script: document.getElementById(`setup-${projectId}`).value,
        default_ro_mounts: defaultMounts.ro_mounts,
        default_rw_mounts: defaultMounts.rw_mounts,
        default_env_vars: defaultEnv,
      };
      await fetchJson(`/api/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      uiDirty = false;
      await refresh();
    }

    async function createChatForProject(projectId) {
      let mountPayload;
      let envPayload;
      try {
        mountPayload = collectMountPayload(`new-volumes-${projectId}`);
        envPayload = collectEnvPayload(`new-env-${projectId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        project_id: projectId,
        profile: document.getElementById(`profile-${projectId}`).value,
        ro_mounts: mountPayload.ro_mounts,
        rw_mounts: mountPayload.rw_mounts,
        env_vars: envPayload,
      };
      await fetchJson('/api/chats', { method: 'POST', body: JSON.stringify(payload) });
      await saveProjectSettings(projectId);
      uiDirty = false;
      await refresh();
    }

    async function startChat(chatId) {
      await fetchJson(`/api/chats/${chatId}/start`, { method: 'POST' });
      await refresh();
    }

    async function closeChat(chatId) {
      await fetchJson(`/api/chats/${chatId}/close`, { method: 'POST' });
      await refresh();
    }

    async function deleteChat(chatId) {
      await fetchJson(`/api/chats/${chatId}`, { method: 'DELETE' });
      await refresh();
    }

    async function deleteProject(projectId) {
      if (!confirm('Delete this project and all chats? This removes stored clones.')) return;
      await fetchJson(`/api/projects/${projectId}`, { method: 'DELETE' });
      await refresh();
    }

    async function updateChat(chatId) {
      let mountPayload;
      let envPayload;
      try {
        mountPayload = collectMountPayload(`chat-volumes-${chatId}`);
        envPayload = collectEnvPayload(`chat-env-${chatId}`);
      } catch (err) {
        alert(err.message || String(err));
        return;
      }
      const payload = {
        profile: document.getElementById(`chat-profile-${chatId}`).value,
        ro_mounts: mountPayload.ro_mounts,
        rw_mounts: mountPayload.rw_mounts,
        env_vars: envPayload,
      };
      await fetchJson(`/api/chats/${chatId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      uiDirty = false;
      await refresh();
    }

    async function viewLog(chatId) {
      const el = document.getElementById(`log-${chatId}`);
      const text = await fetchText(`/api/chats/${chatId}/logs`);
      el.textContent = text || '';
    }

    updateBasePlaceholderForCreate();
    seedVolumeRows('project-default-volumes', [], []);
    seedEnvRows('project-default-env', []);
    refresh();
  </script>
</body>
</html>
    """


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


for _name, _member in list(HubStateRuntimeMixin.__dict__.items()):
    if _name.startswith("__"):
        continue
    if isinstance(_member, staticmethod):
        _fn = _member.__func__
        setattr(HubStateRuntimeMixin, _name, staticmethod(_wrap_sync(_fn)))
        continue
    if isinstance(_member, classmethod):
        _fn = _member.__func__
        setattr(HubStateRuntimeMixin, _name, classmethod(_wrap_sync(_fn)))
        continue
    if callable(_member):
        setattr(HubStateRuntimeMixin, _name, _wrap_sync(_member))
