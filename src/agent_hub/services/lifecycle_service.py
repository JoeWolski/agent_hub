from __future__ import annotations

from importlib import import_module
from collections.abc import Callable
from typing import Any


class LifecycleService:
    def __init__(
        self,
        *,
        forward_openai_account_callback_fn: Callable[..., dict[str, Any]],
        shutdown_fn: Callable[[], dict[str, int]],
    ) -> None:
        self._forward_openai_account_callback_fn = forward_openai_account_callback_fn
        self._shutdown_fn = shutdown_fn

    def forward_openai_account_callback(
        self,
        query: str,
        *,
        path: str = "/auth/callback",
        request_host: str = "",
        request_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._forward_openai_account_callback_fn(
            query,
            path=path,
            request_host=request_host,
            request_context=request_context,
        )

    def shutdown(self) -> dict[str, int]:
        return self._shutdown_fn()

    @staticmethod
    def _hub_server_module() -> Any:
        return import_module("agent_hub.server")

    def _reconcile_startup_chat_runtime_state(
        self,
        state_runtime: Any,
        state: dict[str, Any],
    ) -> tuple[int, int, bool]:
        hub_server = self._hub_server_module()
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
            process_running = bool(has_pid and hub_server._is_process_running(pid))
            if process_running and isinstance(pid, int):
                hub_server._stop_process(pid)
                stopped_chat_processes += 1

            normalized_status = hub_server._normalize_chat_status(chat.get("status"))
            status_requires_failure = normalized_status in {
                hub_server.CHAT_STATUS_RUNNING,
                hub_server.CHAT_STATUS_STARTING,
            }
            if not has_pid and not status_requires_failure:
                continue

            if status_requires_failure:
                state_runtime._transition_chat_status(
                    chat_id,
                    chat,
                    hub_server.CHAT_STATUS_FAILED,
                    hub_server.CHAT_STATUS_REASON_STARTUP_RECONCILE_ORPHAN_PROCESS
                    if has_pid
                    else hub_server.CHAT_STATUS_REASON_STARTUP_RECONCILE_PROCESS_MISSING,
                )
                if not str(chat.get("start_error") or "").strip():
                    chat["start_error"] = (
                        "Recovered from stale chat runtime state during startup."
                        if has_pid
                        else "Chat runtime process was missing during startup reconciliation."
                    )

            if has_pid:
                chat["pid"] = None
                chat["last_exit_code"] = hub_server._normalize_optional_int(chat.get("last_exit_code"))
                chat["last_exit_at"] = hub_server._iso_now()
            else:
                chat["last_exit_code"] = hub_server._normalize_optional_int(chat.get("last_exit_code"))
                if not str(chat.get("last_exit_at") or "").strip():
                    chat["last_exit_at"] = hub_server._iso_now()
            chat["artifact_publish_token_hash"] = ""
            chat["artifact_publish_token_issued_at"] = ""
            chat["agent_tools_token_hash"] = ""
            chat["agent_tools_token_issued_at"] = ""
            chat["stop_requested_at"] = ""
            chat["updated_at"] = hub_server._iso_now()
            state["chats"][chat_id] = chat
            changed = True
            reconciled_chats += 1
        return stopped_chat_processes, reconciled_chats, changed

    def startup_reconcile(self, state_runtime: Any) -> dict[str, int]:
        hub_server = self._hub_server_module()
        state = state_runtime.load()
        stopped_chat_processes, reconciled_chats, state_changed = self._reconcile_startup_chat_runtime_state(
            state_runtime,
            state,
        )
        if state_changed:
            state_runtime.save(state, reason="startup_reconcile")

        removed_orphan_chat_paths = state_runtime._remove_orphan_children(
            state_runtime.chat_dir,
            state_runtime._managed_chat_workspace_paths(state),
        )
        state_runtime._remove_orphan_children(
            state_runtime.chat_artifacts_dir,
            state_runtime._managed_chat_artifact_paths(state),
        )
        removed_orphan_project_paths = state_runtime._remove_orphan_children(
            state_runtime.project_dir,
            state_runtime._managed_project_workspace_paths(state),
        )
        state_runtime._remove_orphan_children(
            state_runtime.runtime_project_tmp_dir,
            state_runtime._managed_project_tmp_paths(state),
        )
        projects = state.get("projects")
        if isinstance(projects, dict):
            for project_id in projects.keys():
                state_runtime._remove_orphan_children(
                    state_runtime.runtime_project_tmp_dir / str(project_id),
                    state_runtime._managed_project_tmp_children_paths(state, str(project_id)),
                )
        removed_orphan_log_entries = state_runtime._remove_orphan_log_entries(state)
        removed_stale_docker_containers = hub_server._docker_remove_stale_containers(
            hub_server.STARTUP_STALE_DOCKER_CONTAINER_PREFIXES
        )

        return {
            "stopped_chat_processes": stopped_chat_processes,
            "reconciled_chats": reconciled_chats,
            "removed_orphan_chat_paths": removed_orphan_chat_paths,
            "removed_orphan_project_paths": removed_orphan_project_paths,
            "removed_orphan_log_entries": removed_orphan_log_entries,
            "removed_stale_docker_containers": removed_stale_docker_containers,
        }

    def clean_start(self, state_runtime: Any) -> dict[str, int]:
        hub_server = self._hub_server_module()
        state_runtime.cancel_openai_account_login()
        state = state_runtime.load()

        runtime_ids = state_runtime.runtime_domain.runtime_ids()
        for chat_id in runtime_ids:
            state_runtime._close_runtime(chat_id)

        stopped_chats = 0
        image_tags: set[str] = set()
        for chat in state["chats"].values():
            pid = chat.get("pid")
            if isinstance(pid, int) and hub_server._is_process_running(pid):
                hub_server._stop_process(pid)
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
            project["updated_at"] = hub_server._iso_now()

        cleared_chats = len(state["chats"])
        state["chats"] = {}

        for path in [
            state_runtime.chat_dir,
            state_runtime.project_dir,
            state_runtime.log_dir,
            state_runtime.runtime_tmp_dir,
            state_runtime.artifacts_dir,
        ]:
            if path.exists():
                state_runtime._delete_path(path)
            path.mkdir(parents=True, exist_ok=True)
        state_runtime.runtime_project_tmp_dir.mkdir(parents=True, exist_ok=True)
        state_runtime.chat_artifacts_dir.mkdir(parents=True, exist_ok=True)
        state_runtime.session_artifacts_dir.mkdir(parents=True, exist_ok=True)

        state_runtime.save(state)
        hub_server._docker_remove_images(("agent-hub-setup-", "agent-base-"), image_tags)

        return {
            "stopped_chats": stopped_chats,
            "cleared_chats": cleared_chats,
            "projects_reset": projects_reset,
            "docker_images_requested": len(image_tags),
        }
