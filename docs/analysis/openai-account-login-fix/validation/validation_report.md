# Validation Report: OpenAI Account Login Callback Fix

## Scope
- Callback success forwarding path.
- 502 failure path classification.
- Callback host/port derivation edge cases.
- Durable logging coverage with redaction controls.

## Baseline Reproduction (Before Fix Behavior)
- Deterministic script reproduced callback forwarding failure:
  - `STATUS 502`
  - Attempted origins: `127.0.0.1`, `localhost`, request host, `host.docker.internal`
  - Bridge gateway host was not attempted.

## Post-Fix Verification
- Deterministic script with bridge discovery path confirmed success:
  - `STATUS 200`
  - `TARGET http://172.17.0.1:1455`
  - Attempt list now includes bridge gateway fallback target.

## Test Results
- Targeted callback suite: `9 passed, 308 deselected`.
- Includes:
  - callback proxy success path
  - fallback to request/artifact/default/bridge hosts
  - explicit 502 classification and logging assertions
  - forwarded-header context parsing
  - host/port parsing edge coverage (host:port, IPv6:port, invalid host)

## Notes
- During implementation, one incremental failure was intentionally caught and fixed:
  - unredacted query values appeared in target URL logs.
  - resolved by redacting logged query values while preserving upstream target visibility.
