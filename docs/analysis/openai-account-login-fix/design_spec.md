# Design Spec: OpenAI Account Callback Forwarding

## Design Goals
- Preserve existing working callback host resolution order.
- Add deterministic bridge-route fallback for Docker-in-Docker host-network callback targets.
- Emit actionable, redacted diagnostics for every callback forwarding decision and failure.

## Non-Goals
- No behavior changes to successful existing auth paths beyond additional fallback attempts and logging.
- No secret-bearing log output.

## Interfaces
- Added request context parsing:
  - `_openai_callback_request_context_from_request(request)`
- Added forwarding utilities:
  - `_parse_callback_forward_host_port(...)`
  - `_discover_openai_callback_bridge_hosts(...)`
  - `_classify_openai_callback_forward_error(...)`
  - `_redact_url_query_values(...)`
- Extended callback forward method:
  - `HubState.forward_openai_account_callback(..., request_context: dict[str, Any] | None = None)`

## Data Flow
1. Callback API route parses forwarded/proxy headers and normalized host/port context.
2. Callback forwarder builds candidate hosts in stable order:
   - `127.0.0.1`, `localhost`, request/client/forwarded hosts, artifact host, default alias/resolution.
3. If unresolved, bridge discovery appends Linux default gateway and Docker bridge gateway.
4. Upstream callback request attempts each candidate with timeout.
5. Structured logs capture:
   - callback URL resolution and candidates
   - forwarded host/scheme/port parsing
   - bridge discovery metadata
   - upstream target/status/error class
   - explicit final failure reason category
6. Sensitive query values remain redacted in all log lines.

## Build/Test Impact
- `src/agent_hub/server.py`
- `tests/test_hub_and_cli.py`

## Rollback Plan
- Revert callback-forward helper additions and signature extension.
- Keep route passing only `request_host`.
- Remove new tests tied to bridge fallback and diagnostics.
