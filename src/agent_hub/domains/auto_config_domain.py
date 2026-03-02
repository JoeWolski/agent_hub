from __future__ import annotations

from typing import Any


class AutoConfigDomain:
    def __init__(self, *, state: Any) -> None:
        self._state = state

    def auto_configure_project(
        self,
        *,
        repo_url: Any,
        default_branch: Any = None,
        request_id: Any = None,
        agent_type: Any = None,
        agent_args: Any = None,
    ) -> dict[str, Any]:
        return self._state.auto_configure_project(
            repo_url=repo_url,
            default_branch=default_branch,
            request_id=request_id,
            agent_type=agent_type,
            agent_args=agent_args,
        )

    def cancel_auto_configure_project(self, *, request_id: Any) -> dict[str, Any]:
        return self._state.cancel_auto_configure_project(request_id=request_id)

