from __future__ import annotations

from typing import Any


class ProjectService:
    def __init__(self, *, domain: Any) -> None:
        self._domain = domain

    def create_project(self, **kwargs: Any) -> dict[str, Any]:
        return self._domain.create_project(**kwargs)

    def update_project(self, project_id: str, update: dict[str, Any]) -> dict[str, Any]:
        return self._domain.update_project(project_id, update)

    def credential_binding_payload(self, project_id: str) -> dict[str, Any]:
        return self._domain.credential_binding_payload(project_id)

    def attach_project_credentials(self, *, project_id: str, mode: Any, credential_ids: Any, source: str) -> dict[str, Any]:
        return self._domain.attach_project_credentials(
            project_id=project_id,
            mode=mode,
            credential_ids=credential_ids,
            source=source,
        )

    def delete_project(self, project_id: str) -> None:
        self._domain.delete_project(project_id)

    def cancel_project_build(self, project_id: str) -> dict[str, Any]:
        return self._domain.cancel_project_build(project_id)

    def project_build_logs(self, project_id: str) -> str:
        return self._domain.project_build_logs(project_id)

    def project_launch_profile(self, project_id: str) -> dict[str, Any]:
        return self._domain.project_launch_profile(project_id)

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
        return self._domain.create_and_start_chat(project_id, **start_kwargs)


__all__ = ["ProjectService"]
