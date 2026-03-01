## Summary
Fixes OpenAI account login callback failures ending in `502 Bad Gateway` by adding deterministic callback forwarding with strong diagnostics and redaction, prioritizing direct CLI user reliability.

## Changes
- Root-cause fix for callback forwarding path:
  - Added bridge-aware host discovery (Linux default route + Docker bridge gateway).
  - Added in-container loopback callback forwarding via `docker exec` and made it primary.
  - Preserved network host forwarding as fallback when container-loopback forwarding fails.
- Added forwarding-context parsing from callback request headers:
  - `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Port`, `Host`, and client host normalization.
- Added durable logging for the full flow:
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
  - container-loopback primary success path
  - network fallback when container-loopback fails
  - callback host/port derivation edge cases (host:port, IPv6:port, invalid host)
  - callback route forwarding-context parsing

## Validation
- `/workspace/agent_hub_writable/.venv/bin/python - <<'PY' [pre-fix repro script]` -> PASS (observed `STATUS 502` with no bridge target attempted)
- `/workspace/agent_hub_writable/.venv/bin/python - <<'PY' [post-fix repro script]` -> PASS (observed `STATUS 200`, target `http://172.17.0.1:1455`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "forward_openai_account_callback"` -> PASS (`8 passed, 311 deselected`)
- `/workspace/agent_hub_writable/.venv/bin/pytest -q tests/test_hub_and_cli.py -k "openai_account_callback_route or parse_callback_forward_host_port"` -> PASS (`3 passed, 316 deselected`)
- Incremental fix checks recorded in `docs/analysis/openai-account-login-fix/validation/manifest.txt`.

## Risks
- `docker exec` is now on the primary callback path; environments that restrict exec into runtime containers will rely on network fallback.
- Non-standard network overlays may still require additional host discovery candidates.
- Additional callback diagnostics increase log volume during auth attempts; logs remain request-scoped and values are redacted.
