## Summary
Fixes OpenAI account login callback failures that ended in `502 Bad Gateway` by adding deterministic Docker bridge fallback routing and comprehensive redacted diagnostics across callback resolution/forwarding.

## Changes
- Root-cause fix in callback forwarding path:
  - Added bridge-aware fallback host discovery when localhost/request/default hosts fail.
  - Added Linux default-route gateway and Docker bridge gateway discovery.
  - Preserved existing host candidate order and behavior for currently working flows.
- Added forwarding-context parsing from callback request headers:
  - `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Port`, `Host`, and client host normalization.
- Added durable logging for the entire flow:
  - callback URL resolution decisions
  - forwarded host/scheme/port parsing
  - bridge routing diagnostics
  - upstream request target + response status + timeout/error class
  - explicit categorized terminal failure reason
- Added secret-safety controls:
  - callback query value summaries only
  - redacted query values in logged target URLs
  - no logging of code/code_verifier/access_token-like values
- Added targeted tests for:
  - callback success path
  - 502-producing failure path + failure-category logs + redaction
  - bridge fallback success path
  - callback host/port derivation edge cases (host:port, IPv6:port, invalid host)
  - callback route forwarding-context parsing

## Validation
- `/workspace/agent_hub_writable/.venv/bin/python - <<'PY' [pre-fix repro script]` -> PASS (observed `STATUS 502` with no bridge target attempted)
- `/workspace/agent_hub_writable/.venv/bin/python - <<'PY' [post-fix repro script]` -> PASS (observed `STATUS 200`, target `http://172.17.0.1:1455`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback or openai_account_callback_route or parse_callback_forward_host_port"` -> PASS (`9 passed, 308 deselected`)
- Incremental fix checks recorded in `docs/analysis/openai-account-login-fix/validation/manifest.txt`.

## Risks
- Network environments with non-standard host routing beyond default-route/bridge detection may still require additional fallback candidates.
- Additional callback diagnostics increase log volume during auth attempts; logs remain bounded by request scope and values are redacted.
