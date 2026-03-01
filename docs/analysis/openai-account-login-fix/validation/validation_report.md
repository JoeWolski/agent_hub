# Validation Report: OpenAI Account Login Callback Fix

## Scope
- Callback success forwarding path.
- 502 failure path classification.
- Callback host/port derivation edge cases.
- Durable logging coverage with redaction controls.
- Primary callback strategy for direct CLI user flow.

## Baseline Reproduction (Before Fix Behavior)
- Deterministic script reproduced callback forwarding failure:
  - `STATUS 502`
  - Attempted origins: `127.0.0.1`, `localhost`, request host, `host.docker.internal`
  - Bridge gateway host was not attempted.

## Post-Fix Verification
- Deterministic script with bridge discovery path confirmed success:
  - `STATUS 200`
  - `TARGET http://172.17.0.1:1455`
  - Attempt list includes bridge gateway fallback target.
- Strategy update validated:
  - Callback now attempts in-container loopback first (primary), then network candidates.
  - Network candidate path remains as fallback when container-exec path fails.

## Test Results
- Callback forwarding targeted suite (updated strategy): `8 passed, 311 deselected`.
- Route and parsing targeted suite: `3 passed, 316 deselected`.
- Coverage includes:
  - callback proxy success path
  - fallback to request/artifact/default/bridge hosts
  - explicit 502 classification and logging assertions
  - forwarded-header context parsing
  - host/port parsing edge coverage (host:port, IPv6:port, invalid host)
  - container-loopback primary success path
  - network fallback after container-loopback failure

## Notes
- During implementation, one incremental failure was intentionally caught and fixed:
  - unredacted query values appeared in target URL logs.
  - resolved by redacting logged query values while preserving upstream target visibility.
