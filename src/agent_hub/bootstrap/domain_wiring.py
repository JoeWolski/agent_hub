from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class HubDomainServiceBundle:
    settings_service: Any
    launch_profile_service: Any
    auth_domain: Any
    credentials_domain: Any
    runtime_domain: Any
    auth_service: Any
    project_service: Any
    chat_service: Any
    runtime_service: Any
    credentials_service: Any
    artifacts_service: Any
    auto_config_service: Any
    app_state_service: Any
    event_service: Any
    openai_account_service: Any
    lifecycle_service: Any

    def apply_to_state(self, state: Any) -> None:
        state.settings_service = self.settings_service
        state.launch_profile_service = self.launch_profile_service
        state.auth_domain = self.auth_domain
        state.credentials_domain = self.credentials_domain
        state.runtime_domain = self.runtime_domain
        state._runtime_lock = self.runtime_domain._runtime_lock
        state._chat_runtimes = self.runtime_domain._chat_runtimes
        state.auth_service = self.auth_service
        state.project_service = self.project_service
        state.chat_service = self.chat_service
        state.runtime_service = self.runtime_service
        state.credentials_service = self.credentials_service
        state.artifacts_service = self.artifacts_service
        state.auto_config_service = self.auto_config_service
        state.app_state_service = self.app_state_service
        state.event_service = self.event_service
        state.openai_account_service = self.openai_account_service
        state.lifecycle_service = self.lifecycle_service


def build_hub_domain_service_bundle(
    *,
    state: Any,
    settings_service_factory: Callable[..., Any],
    launch_profile_service_factory: Callable[..., Any],
    auth_domain_factory: Callable[..., Any],
    credentials_domain_factory: Callable[..., Any],
    runtime_domain_factory: Callable[..., Any],
    auth_service_factory: Callable[..., Any],
    project_service_factory: Callable[..., Any],
    chat_service_factory: Callable[..., Any],
    runtime_service_factory: Callable[..., Any],
    credentials_service_factory: Callable[..., Any],
    artifacts_service_factory: Callable[..., Any],
    auto_config_service_factory: Callable[..., Any],
    app_state_service_factory: Callable[..., Any],
    event_service_factory: Callable[..., Any],
    openai_account_service_factory: Callable[..., Any],
    lifecycle_service_factory: Callable[..., Any],
    default_agent_type: str,
    default_chat_layout_engine: str,
    normalize_chat_agent_type: Callable[[str], str],
    normalize_chat_layout_engine: Callable[[str], str],
    runtime_factory: Any,
    is_process_running: Callable[[int], bool],
    signal_process_group_winch: Callable[[int], None],
    terminal_queue_max: int,
    default_cols: int,
    default_rows: int,
    default_artifact_publish_host: str,
    callback_forward_timeout_seconds: float,
    agent_tools_token_header: str,
    artifact_token_header: str,
    logger: Any,
    default_agent_image: str,
    openai_account_login_default_callback_port: int,
    openai_account_login_log_max_chars: int,
    forward_openai_callback_via_container_loopback_fn: Callable[..., Any],
    ansi_escape_re: Any,
    tmp_dir_tmpfs_spec: str,
    default_container_home: str,
    stop_process: Callable[[int], None],
    parse_gid_csv: Callable[[str], list[int]],
    iso_now: Callable[[], str],
    normalize_openai_account_login_method: Callable[[str], str],
    docker_image_exists: Callable[[str], bool],
    discover_bridge_hosts: Callable[[], list[str]],
    normalize_callback_forward_host: Callable[[str], str],
    openai_callback_query_summary: Callable[[str], str],
    redact_url_query_values: Callable[[str], str],
    host_port_netloc: Callable[[str, int], str],
    classify_callback_error: Callable[[Exception], tuple[str, str]],
    append_tail: Callable[[str, str, int], str],
    short_summary: Callable[..., str],
    first_url_in_text: Callable[[str, str], str],
    parse_local_callback: Callable[[str], tuple[str, int, str]],
    openai_login_url_in_text: Callable[[str], str],
    read_codex_auth: Callable[[Any], dict[str, Any]],
    read_openai_api_key: Callable[[Any], str],
    mask_secret: Callable[[str], str],
    iso_from_timestamp: Callable[[float], str],
    normalize_openai_api_key: Callable[[str], str],
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
) -> HubDomainServiceBundle:
    settings_service = settings_service_factory(
        default_agent_type=default_agent_type,
        default_chat_layout_engine=default_chat_layout_engine,
        normalize_chat_agent_type=normalize_chat_agent_type,
        normalize_chat_layout_engine=normalize_chat_layout_engine,
    )
    launch_profile_service = launch_profile_service_factory(state=state)
    auth_domain = auth_domain_factory(state=state)
    credentials_domain = credentials_domain_factory(state=state)
    runtime_domain = runtime_domain_factory(
        runtime_factory=runtime_factory,
        is_process_running=lambda pid: is_process_running(pid),
        signal_process_group_winch=lambda pid: signal_process_group_winch(pid),
        chat_log_path=state.chat_log,
        on_runtime_exit=lambda chat_id, exit_code: state._record_chat_runtime_exit(
            chat_id,
            exit_code,
            reason="chat_runtime_reader_completed",
        ),
        collect_submitted_prompts=state._collect_submitted_prompts_from_input,
        record_submitted_prompt=state._record_submitted_prompt,
        terminal_queue_max=terminal_queue_max,
        default_cols=default_cols,
        default_rows=default_rows,
    )
    auth_service = auth_service_factory(
        domain=auth_domain,
        default_artifact_publish_host=default_artifact_publish_host,
        callback_forward_timeout_seconds=callback_forward_timeout_seconds,
    )
    project_service = project_service_factory(state=state)
    chat_service = chat_service_factory(state=state)
    runtime_service = runtime_service_factory(state=state)
    credentials_service = credentials_service_factory(
        domain=credentials_domain,
        agent_tools_token_header=agent_tools_token_header,
    )
    artifacts_service = artifacts_service_factory(
        state=state,
        agent_tools_token_header=agent_tools_token_header,
        artifact_token_header=artifact_token_header,
    )
    auto_config_service = auto_config_service_factory(state=state)
    app_state_service = app_state_service_factory(state=state)
    event_service = event_service_factory(state=state)
    openai_account_service = openai_account_service_factory(
        openai_codex_auth_file=state.openai_codex_auth_file,
        openai_credentials_file=state.openai_credentials_file,
        host_agent_home=state.host_agent_home,
        host_codex_dir=state.host_codex_dir,
        config_file=state.config_file,
        local_uid_getter=lambda: state.local_uid,
        local_gid_getter=lambda: state.local_gid,
        local_supp_gids_getter=lambda: state.local_supp_gids,
        local_user_getter=lambda: state.local_user,
        local_umask_getter=lambda: state.local_umask,
        artifact_publish_base_url_getter=lambda: state.artifact_publish_base_url,
        openai_login_lock=state._openai_login_lock,
        get_openai_login_session=lambda: state._openai_login_session,
        set_openai_login_session=lambda session: setattr(state, "_openai_login_session", session),
        openai_login_session_type=state._openai_login_session_type,
        emit_auth_changed=lambda **kwargs: state._emit_auth_changed(**kwargs),
        emit_openai_account_session_changed=lambda **kwargs: state._emit_openai_account_session_changed(**kwargs),
        auth_forward_openai_account_callback_fn=auth_service.forward_openai_account_callback,
        forward_openai_callback_via_container_loopback_fn=lambda **kwargs: forward_openai_callback_via_container_loopback_fn(
            **kwargs
        ),
        logger=logger,
        default_agent_image=default_agent_image,
        openai_account_login_default_callback_port=openai_account_login_default_callback_port,
        openai_account_login_log_max_chars=openai_account_login_log_max_chars,
        ansi_escape_re=ansi_escape_re,
        tmp_dir_tmpfs_spec=tmp_dir_tmpfs_spec,
        default_container_home=default_container_home,
        is_process_running=lambda pid: is_process_running(pid),
        stop_process=lambda pid: stop_process(pid),
        parse_gid_csv=lambda value: parse_gid_csv(value),
        iso_now=lambda: iso_now(),
        normalize_openai_account_login_method=lambda value: normalize_openai_account_login_method(value),
        docker_image_exists=lambda tag: docker_image_exists(tag),
        discover_bridge_hosts=lambda: discover_bridge_hosts(),
        normalize_callback_forward_host=lambda value: normalize_callback_forward_host(value),
        openai_callback_query_summary=lambda query: openai_callback_query_summary(query),
        redact_url_query_values=lambda url: redact_url_query_values(url),
        host_port_netloc=lambda host, port: host_port_netloc(host, port),
        classify_callback_error=lambda exc: classify_callback_error(exc),
        append_tail=lambda existing, addition, max_chars: append_tail(existing, addition, max_chars),
        short_summary=lambda text, max_words, max_chars: short_summary(text, max_words=max_words, max_chars=max_chars),
        first_url_in_text=lambda text, prefix: first_url_in_text(text, prefix),
        parse_local_callback=lambda value: parse_local_callback(value),
        openai_login_url_in_text=lambda text: openai_login_url_in_text(text),
        read_codex_auth=lambda path: read_codex_auth(path),
        read_openai_api_key=lambda path: read_openai_api_key(path),
        mask_secret=lambda value: mask_secret(value),
        iso_from_timestamp=lambda ts: iso_from_timestamp(ts),
        normalize_openai_api_key=lambda value: normalize_openai_api_key(value),
        verify_openai_api_key=lambda value: verify_openai_api_key(value),
        write_private_env_file=lambda path, content: write_private_env_file(path, content),
        openai_generate_chat_title=lambda **kwargs: openai_generate_chat_title(**kwargs),
        codex_generate_chat_title=lambda **kwargs: codex_generate_chat_title(**kwargs),
        chat_title_openai_model=chat_title_openai_model,
        chat_title_account_model=chat_title_account_model,
        chat_title_auth_mode_account=chat_title_auth_mode_account,
        chat_title_auth_mode_api_key=chat_title_auth_mode_api_key,
        chat_title_auth_mode_none=chat_title_auth_mode_none,
        chat_title_no_credentials_error=chat_title_no_credentials_error,
        chat_title_max_chars=chat_title_max_chars,
    )
    lifecycle_service = lifecycle_service_factory(
        forward_openai_account_callback_fn=openai_account_service.forward_openai_account_callback,
        shutdown_fn=state.shutdown,
    )
    return HubDomainServiceBundle(
        settings_service=settings_service,
        launch_profile_service=launch_profile_service,
        auth_domain=auth_domain,
        credentials_domain=credentials_domain,
        runtime_domain=runtime_domain,
        auth_service=auth_service,
        project_service=project_service,
        chat_service=chat_service,
        runtime_service=runtime_service,
        credentials_service=credentials_service,
        artifacts_service=artifacts_service,
        auto_config_service=auto_config_service,
        app_state_service=app_state_service,
        event_service=event_service,
        openai_account_service=openai_account_service,
        lifecycle_service=lifecycle_service,
    )
