from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ProjectDomain:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def create_project(self, **kwargs: Any) -> dict[str, Any]:
        return self._state.add_project(**kwargs)

    def update_project(self, project_id: str, update: dict[str, Any]) -> dict[str, Any]:
        return self._state.update_project(project_id, update)

    def credential_binding_payload(self, project_id: str) -> dict[str, Any]:
        return self._state.project_credential_binding_payload(project_id)

    def attach_project_credentials(self, *, project_id: str, mode: Any, credential_ids: Any, source: str) -> dict[str, Any]:
        return self._state.attach_project_credentials(
            project_id=project_id,
            mode=mode,
            credential_ids=credential_ids,
            source=source,
        )

    def delete_project(self, project_id: str) -> None:
        self._state.delete_project(project_id)

    def cancel_project_build(self, project_id: str) -> dict[str, Any]:
        return self._state.cancel_project_build(project_id)

    def project_build_logs(self, project_id: str) -> str:
        project = self._state.project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found.")
        log_path = self._state.project_build_log(project_id)
        if not log_path.exists():
            return ""
        return log_path.read_text(encoding="utf-8", errors="ignore")

    def project_launch_profile(self, project_id: str) -> dict[str, Any]:
        return self._state.project_snapshot_launch_profile(project_id)

    def create_and_start_chat(
        self,
        project_id: str,
        *,
        agent_args: list[str],
        agent_type: str,
        request_id: str = "",
    ) -> dict[str, Any]:
        start_kwargs: dict[str, Any] = {
            "agent_args": agent_args,
            "agent_type": agent_type,
        }
        if request_id:
            start_kwargs["request_id"] = request_id
        return self._state.create_and_start_chat(project_id, **start_kwargs)

