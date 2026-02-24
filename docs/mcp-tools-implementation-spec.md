# MCP Tooling Spec For Faster Cross-Layer Refactors

## Purpose
This document specifies MCP tools that would have significantly reduced implementation time and risk for large cross-layer auth refactors (backend routes/state, frontend API usage, tests, UI evidence, and PR workflow).

The specs are written so a future agent can implement these tools directly with minimal ambiguity.

## Shared Conventions
- Transport: MCP `tools/list` + `tools/call` JSON-RPC over stdio.
- Input format: strict JSON object validated before execution.
- Output format: strict JSON object; no plain-text-only responses.
- Determinism: tools must support a deterministic mode via `deterministic=true`.
- Paths: all file paths are absolute in outputs.
- Time: all timestamps RFC3339 UTC.
- Errors: every tool returns structured errors as `{ code, message, retriable, details }`.
- Safety: no destructive git/file operations unless `allow_destructive=true` is explicitly provided.

---

## 1) `repo_impact.map_change`

### Problem It Solves
Identify all likely backend/frontend/test/docs touch points for a symbol/route/schema change.

### Ideal Input
```json
{
  "targets": [
    {
      "kind": "symbol",
      "value": "connect_github_personal_access_token"
    },
    {
      "kind": "route",
      "value": "/api/settings/auth/github-tokens/connect"
    }
  ],
  "repo_root": "/workspace/agent_hub",
  "languages": ["python", "javascript"],
  "include_tests": true,
  "include_docs": true,
  "max_results": 500,
  "deterministic": true
}
```

### Function
- Build symbol and route index from repository.
- Resolve direct references (definition/calls/imports/string literals).
- Resolve indirect references via:
- FastAPI decorators and handler call chains.
- Frontend fetch call sites and helper wrappers.
- Test fixtures/helpers that target changed routes/payloads.
- Emit ranked impact graph with confidence and reason.

### Output
```json
{
  "summary": {
    "target_count": 2,
    "files_impacted": 17,
    "tests_impacted": 8,
    "high_risk_edges": 5
  },
  "impacts": [
    {
      "file": "/workspace/agent_hub/src/agent_hub/server.py",
      "kind": "definition",
      "line": 6578,
      "confidence": 1.0,
      "reason": "Exact symbol definition"
    },
    {
      "file": "/workspace/agent_hub/web/src/App.jsx",
      "kind": "api_call_site",
      "line": 3001,
      "confidence": 0.98,
      "reason": "fetchJson route literal"
    }
  ],
  "graph": {
    "nodes": ["..."],
    "edges": ["..."]
  },
  "errors": []
}
```

### Side Effects
- None.

### Failure Modes
- `INDEX_BUILD_FAILED`: parser/index unavailable.
- `TARGET_NOT_FOUND`: none of targets resolved.

---

## 2) `fastapi_frontend_contract.diff`

### Problem It Solves
Detect drift between FastAPI route contracts and frontend usage.

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "backend": {
    "framework": "fastapi",
    "entrypoint": "/workspace/agent_hub/src/agent_hub/server.py"
  },
  "frontend": {
    "fetch_wrappers": ["fetchJson"],
    "roots": ["/workspace/agent_hub/web/src"]
  },
  "compare": {
    "method": true,
    "path": true,
    "request_shape": true,
    "response_shape": true
  },
  "deterministic": true
}
```

### Function
- Extract backend route table: method/path/handler/request-model/response-shape.
- Extract frontend request table: method/path literals/templates/expected response fields.
- Match routes and detect:
- Missing backend route for frontend caller.
- Missing frontend caller migration for renamed route.
- Payload field mismatches.
- Optional vs required field mismatches.

### Output
```json
{
  "drift_count": 3,
  "drifts": [
    {
      "type": "missing_route",
      "frontend_file": "/workspace/agent_hub/web/src/App.jsx",
      "line": 2973,
      "method": "POST",
      "path": "/api/settings/auth/github/connect",
      "suggested_fix": "Use /api/settings/auth/github-app/connect"
    }
  ],
  "route_inventory": {
    "backend_routes": 98,
    "frontend_calls": 76,
    "matched": 73
  },
  "errors": []
}
```

### Side Effects
- None.

### Failure Modes
- `BACKEND_PARSE_FAILED`.
- `FRONTEND_PARSE_FAILED`.

---

## 3) `state_invariant.check`

### Problem It Solves
Validate critical state invariants across transitions (especially disconnect isolation).

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "runtime": {
    "kind": "python_inproc",
    "state_factory": "agent_hub.server.HubState"
  },
  "fixtures": {
    "data_dir": "/tmp/invariant-check",
    "config_file": "/tmp/invariant-check/config.toml"
  },
  "invariants": [
    {
      "name": "github_app_disconnect_isolated",
      "arrange": ["connect_github_app", "connect_github_token", "connect_gitlab_token"],
      "act": "disconnect_github_app",
      "assert": [
        "github_app.connected == false",
        "github_tokens.token_count == 1",
        "gitlab_tokens.token_count == 1"
      ]
    }
  ],
  "deterministic": true
}
```

### Function
- Instantiate clean state.
- Execute arrange-act-assert invariant scenarios.
- Return pass/fail with before/after state diffs and violation traces.

### Output
```json
{
  "invariant_results": [
    {
      "name": "github_app_disconnect_isolated",
      "passed": true,
      "before_hash": "sha256:...",
      "after_hash": "sha256:...",
      "violations": []
    }
  ],
  "summary": {
    "total": 1,
    "passed": 1,
    "failed": 0
  },
  "errors": []
}
```

### Side Effects
- Temporary local files under provided fixture dir only.

### Failure Modes
- `SCENARIO_EXEC_FAILED` with stack trace.
- `ASSERTION_PARSE_FAILED`.

---

## 4) `auth_fixture.seed_matrix`

### Problem It Solves
Create deterministic auth-state matrices for local tests and UI evidence without manual credential setup.

### Ideal Input
```json
{
  "output_root": "/tmp/agent-hub-auth-matrix",
  "profiles": [
    "none",
    "github_app_only",
    "github_tokens_only",
    "gitlab_tokens_only",
    "all_connected"
  ],
  "include_openai_account_stub": true,
  "github_app": {
    "generate_valid_rsa_key": true,
    "installation_id": 424242,
    "account_login": "acme-org"
  },
  "token_defaults": {
    "github_host": "github.com",
    "gitlab_host": "gitlab.com"
  },
  "deterministic": true,
  "seed": "agent-hub-auth-v1"
}
```

### Function
- Produce data-dir variants with correctly named secret files and valid schema.
- Optionally generate a valid RSA PEM for GitHub App JWT signing.
- Optionally emit a mock GitHub API server config for installation list endpoint.

### Output
```json
{
  "profiles": [
    {
      "name": "all_connected",
      "data_dir": "/tmp/agent-hub-auth-matrix/all_connected",
      "files": [
        "/tmp/agent-hub-auth-matrix/all_connected/secrets/github_app_settings.json",
        "/tmp/agent-hub-auth-matrix/all_connected/secrets/github_app_installation.json",
        "/tmp/agent-hub-auth-matrix/all_connected/secrets/github_tokens.json",
        "/tmp/agent-hub-auth-matrix/all_connected/secrets/gitlab_tokens.json"
      ]
    }
  ],
  "mock_services": [
    {
      "name": "mock_github_installations_api",
      "start_command": "python /tmp/.../mock_github_api.py",
      "base_url": "http://127.0.0.1:9123"
    }
  ],
  "errors": []
}
```

### Side Effects
- Writes only under `output_root`.

### Failure Modes
- `KEY_GENERATION_FAILED`.
- `PROFILE_WRITE_FAILED`.

---

## 5) `ui_evidence.capture_states`

### Problem It Solves
Automate real-backend screenshot capture for required UI states.

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "server": {
    "command": "UV_PROJECT_ENVIRONMENT=.venv-local uv run agent_hub --host 127.0.0.1 --port {{port}} --data-dir {{data_dir}} --config-file {{config_file}} --system-prompt-file {{system_prompt}} --frontend-build",
    "ports": [8876, 8877]
  },
  "states": [
    {
      "name": "settings_auth_disconnected",
      "data_dir": "/tmp/agent-hub-auth-matrix/none",
      "url": "http://127.0.0.1:8876",
      "assert_absent_text": ["{\"detail\""],
      "actions": [
        {"type": "click_role", "role": "button", "name": "Settings"}
      ],
      "wait_for": [
        {"type": "heading", "name": "GitHub", "exact": true},
        {"type": "heading", "name": "GitLab", "exact": true}
      ],
      "output_file": "/workspace/agent_hub/.agent-artifacts/settings-auth-disconnected.jpg"
    }
  ],
  "playwright": {
    "browser": "firefox",
    "viewport": {"width": 1720, "height": 1200},
    "image_type": "jpeg",
    "jpeg_quality": 82
  },
  "upload": {
    "provider": "tmpfiles",
    "enabled": true
  },
  "deterministic": true
}
```

### Function
- Start/stop real server per state scenario.
- Run scripted browser actions/assertions.
- Capture screenshots.
- Optionally upload and return public URLs.
- Verify screenshot validity by OCR/text checks (no obvious error banners unless expected).

### Output
```json
{
  "captures": [
    {
      "name": "settings_auth_disconnected",
      "local_path": "/workspace/agent_hub/.agent-artifacts/settings-auth-disconnected.jpg",
      "public_url": "https://tmpfiles.org/dl/.../settings-auth-disconnected.jpg",
      "passed": true,
      "checks": {
        "assert_absent_text": true,
        "wait_for": true
      }
    }
  ],
  "commands_executed": ["..."],
  "errors": []
}
```

### Side Effects
- Launches local processes.
- Writes image files.
- Network upload if enabled.

### Failure Modes
- `SERVER_HEALTHCHECK_FAILED`.
- `BROWSER_ASSERTION_FAILED`.
- `UPLOAD_FAILED`.

---

## 6) `tests_refactor.route_migration`

### Problem It Solves
Mass-update tests after route namespace/payload migrations.

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "mappings": [
    {
      "from": "/api/settings/auth/github/connect",
      "to": "/api/settings/auth/github-app/connect"
    },
    {
      "from": "/api/settings/auth/github/disconnect",
      "to": "/api/settings/auth/github-app/disconnect"
    }
  ],
  "payload_field_mappings": [
    {
      "context": "auth.providers",
      "from": "github",
      "to": ["github_app", "github_tokens"]
    }
  ],
  "test_roots": ["/workspace/agent_hub/tests"],
  "dry_run": false,
  "deterministic": true
}
```

### Function
- Detect literal and formatted route usages in tests.
- Rewrite assertions for renamed payload keys based on context mapping.
- Emit patch and confidence; leave low-confidence edits as TODO comments.

### Output
```json
{
  "edits": [
    {
      "file": "/workspace/agent_hub/tests/test_hub_and_cli.py",
      "line": 7499,
      "old": "/api/settings/auth/github/connect",
      "new": "/api/settings/auth/github-app/connect",
      "confidence": 0.99
    }
  ],
  "manual_followups": [
    {
      "file": "/workspace/agent_hub/tests/test_hub_and_cli.py",
      "reason": "Assertion semantic split required",
      "line": 1138
    }
  ],
  "errors": []
}
```

### Side Effects
- File edits if `dry_run=false`.

### Failure Modes
- `WRITE_FAILED`.
- `LOW_CONFIDENCE_BLOCKED` when strict mode enabled.

---

## 7) `mcp_scaffold.secure_proxy`

### Problem It Solves
Generate secure MCP tool server boilerplate that proxies to hub APIs with auth.

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "module_path": "/workspace/agent_hub/src/agent_hub/agent_tools_mcp.py",
  "tool_name_prefix": "agent_tools",
  "upstream": {
    "base_url_env": "AGENT_HUB_AGENT_TOOLS_URL",
    "token_env": "AGENT_HUB_AGENT_TOOLS_TOKEN",
    "auth_header": "Authorization",
    "auth_scheme": "Bearer"
  },
  "tools": [
    {
      "name": "credentials_list",
      "method": "GET",
      "path": "/api/chats/{chat_id}/agent-tools/credentials",
      "input_schema": {
        "type": "object",
        "properties": {
          "chat_id": {"type": "string"}
        },
        "required": ["chat_id"]
      }
    }
  ],
  "deterministic": true
}
```

### Function
- Scaffold MCP JSON-RPC handlers for `initialize`, `tools/list`, `tools/call`.
- Generate typed request validation and upstream HTTP helpers.
- Add safe logging that redacts secrets.

### Output
```json
{
  "files_written": [
    "/workspace/agent_hub/src/agent_hub/agent_tools_mcp.py"
  ],
  "entrypoint_snippet": "agent_tools_mcp = \"agent_hub.agent_tools_mcp:main\"",
  "next_steps": [
    "Register script in pyproject.toml",
    "Add unit tests"
  ],
  "errors": []
}
```

### Side Effects
- Writes scaffold files.

### Failure Modes
- `MODULE_EXISTS_CONFLICT`.
- `SCHEMA_INVALID`.

---

## 8) `process_supervisor.orchestrate`

### Problem It Solves
Deterministically manage multi-process local workflows (hub, mock APIs, browser capture).

### Ideal Input
```json
{
  "workspace": "/workspace/agent_hub",
  "processes": [
    {
      "name": "mock_github_api",
      "cmd": "python /tmp/mock_github_api.py",
      "healthcheck": {
        "type": "http",
        "url": "http://127.0.0.1:9123/app/installations",
        "expect_status": 200
      }
    },
    {
      "name": "hub",
      "cmd": "UV_PROJECT_ENVIRONMENT=.venv-local uv run agent_hub --host 127.0.0.1 --port 8877 ...",
      "healthcheck": {
        "type": "http",
        "url": "http://127.0.0.1:8877/api/state",
        "expect_status": 200
      }
    }
  ],
  "shutdown": {
    "grace_ms": 2000,
    "force_kill_after_ms": 5000
  },
  "deterministic": true
}
```

### Function
- Start processes in dependency order.
- Wait for health checks.
- Stream logs with per-process prefixes.
- Ensure cleanup even on failure/interrupt.

### Output
```json
{
  "run_id": "orch-20260224-1846-001",
  "started": ["mock_github_api", "hub"],
  "healthy": true,
  "pids": {
    "mock_github_api": 8123,
    "hub": 7531
  },
  "errors": []
}
```

### Side Effects
- Starts/stops local processes.

### Failure Modes
- `HEALTHCHECK_TIMEOUT`.
- `PROCESS_EXITED_EARLY`.

---

## 9) `pr_compliance.enforce_repo_policy`

### Problem It Solves
Automatically validate PR and branch policy compliance.

### Ideal Input
```json
{
  "repo_root": "/workspace/agent_hub",
  "pr": {
    "number": 109,
    "required_sections": ["## Summary", "## Changes", "## Validation", "## Risks"],
    "require_ui_demo_for_ui_changes": true,
    "require_draft": true
  },
  "branch_policy": {
    "single_commit": true,
    "rebase_on_default": true,
    "no_merge_commits": true
  },
  "validation_policy": {
    "commands_must_include_status": true
  },
  "deterministic": true
}
```

### Function
- Inspect git history, PR metadata/body, changed files, and validation content.
- Enforce section order/content and UI evidence presence when UI files changed.

### Output
```json
{
  "compliant": true,
  "checks": [
    {"name": "single_commit", "passed": true},
    {"name": "required_sections", "passed": true},
    {"name": "ui_demo_present", "passed": true}
  ],
  "fix_suggestions": [],
  "errors": []
}
```

### Side Effects
- Optional auto-fix mode could patch PR body; default should be read-only.

### Failure Modes
- `PR_METADATA_UNAVAILABLE`.
- `BODY_PARSE_FAILED`.

---

## Cross-Tool Security Requirements
- Secret redaction is mandatory in logs and outputs.
- No token/private key raw values in outputs unless explicitly requested with `allow_secret_output=true`.
- Network destinations must be allowlisted per tool invocation.
- File writes must be restricted to caller-provided roots.

## Cross-Tool Reliability Requirements
- Every tool must expose `deterministic=true` and document any non-deterministic steps.
- Every mutation tool must support `dry_run=true`.
- Every tool must return machine-readable error codes and remediation hints.
- Long-running tools must emit progress checkpoints.

## Suggested Build Order For A Future Agent
1. `repo_impact.map_change`
2. `fastapi_frontend_contract.diff`
3. `state_invariant.check`
4. `auth_fixture.seed_matrix`
5. `ui_evidence.capture_states`
6. `tests_refactor.route_migration`
7. `mcp_scaffold.secure_proxy`
8. `process_supervisor.orchestrate`
9. `pr_compliance.enforce_repo_policy`

## Why This Set Matters
Together, these tools remove the highest-friction manual work in this class of refactor:
- cross-layer discovery,
- contract drift detection,
- state-safety validation,
- repeatable auth state setup,
- deterministic UI evidence,
- test migration,
- secure MCP plumbing,
- process lifecycle control,
- and PR policy enforcement.
