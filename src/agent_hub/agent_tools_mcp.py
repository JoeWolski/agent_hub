from __future__ import annotations

import json
import os
import sys
import traceback
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


TOOL_LIST = [
    {
        "name": "credentials_list",
        "description": (
            "List credential options available for the active repository context, "
            "including current project credential binding and effective selection."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "credentials_resolve",
        "description": (
            "Resolve credentials for the active repository context. "
            "Supported modes: auto, all, set, single."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "credential_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "project_attach_credentials",
        "description": (
            "Attach a credential binding to the backing project so future chats auto-select "
            "the same credential set without manual token ordering."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "credential_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
]


def _env_required(key: str) -> str:
    value = str(os.environ.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _agent_tools_base_url() -> str:
    return _env_required("AGENT_HUB_AGENT_TOOLS_URL").rstrip("/")


def _agent_tools_token() -> str:
    return _env_required("AGENT_HUB_AGENT_TOOLS_TOKEN")


def _api_request(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = _agent_tools_base_url()
    url = f"{base_url}{path}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-agent-hub-agent-tools-token": _agent_tools_token(),
        "Authorization": f"Bearer {_agent_tools_token()}",
        "User-Agent": "agent-tools-mcp/1.0",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, method=method, data=data)
    try:
        with urllib.request.urlopen(request, timeout=20.0) as response:
            body = response.read().decode("utf-8", errors="ignore")
            if not body.strip():
                return {}
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        detail = body.strip() or f"HTTP {exc.code}"
        raise RuntimeError(f"agent_tools API request failed: {method} {url} -> {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"agent_tools API request failed: {method} {url}: {exc}") from exc


def _tool_response(result: Any) -> dict[str, Any]:
    text = json.dumps(result, indent=2, sort_keys=True)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": result,
        "isError": False,
    }


def _tool_error(message: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }


def _handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "credentials_list":
        payload = _api_request("/credentials", method="GET")
        return _tool_response(payload)
    if name == "credentials_resolve":
        body = {
            "mode": arguments.get("mode", "auto"),
            "credential_ids": arguments.get("credential_ids") or [],
        }
        payload = _api_request("/credentials/resolve", method="POST", payload=body)
        return _tool_response(payload)
    if name == "project_attach_credentials":
        body = {
            "mode": arguments.get("mode", "auto"),
            "credential_ids": arguments.get("credential_ids") or [],
        }
        payload = _api_request("/project-binding", method="POST", payload=body)
        return _tool_response(payload)
    return _tool_error(f"Unsupported tool: {name}")


def _write_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _handle_request(request: dict[str, Any]) -> None:
    method = str(request.get("method") or "")
    request_id = request.get("id")
    params = request.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        _write_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "agent_tools", "version": "1.0.0"},
                },
            }
        )
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        _write_json({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOL_LIST}})
        return

    if method == "tools/call":
        name = str(params.get("name") or "")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        try:
            result = _handle_tool_call(name, arguments)
            _write_json({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            _write_json({"jsonrpc": "2.0", "id": request_id, "result": _tool_error(str(exc))})
        return

    if request_id is not None:
        _write_json(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        try:
            _handle_request(parsed)
        except Exception as exc:
            request_id = parsed.get("id")
            if request_id is not None:
                _write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32000,
                            "message": str(exc),
                            "data": traceback.format_exc(limit=2),
                        },
                    }
                )


if __name__ == "__main__":
    main()

