# Verification Plan: OpenAI Account Callback Fix

## Scope
Callback forwarding success/failure handling, host derivation, and log diagnostics.

## Assumptions
- Docker-in-Docker route mismatch can require bridge gateway fallback.
- OAuth callback query values must not be logged.

## Hazards
- False-negative callback routing causing 502.
- Silent failures without diagnosable context.
- Secrets appearing in logs.

## Failure Modes
- `host.docker.internal` unresolved or unreachable.
- Request-host mismatch in proxied environments.
- Upstream callback listener unavailable.

## Required Controls
- Stable candidate host order with additional bridge candidates.
- Forwarded header parsing and logging of derived context.
- Error classification and explicit failure reason in logs.
- Redacted query values in all callback-forward logs.

## Verification Mapping
- Baseline repro script: confirms pre-fix 502 scenario.
- Post-fix repro script: confirms bridge-host success.
- Pytest targeted suite:
  - callback success path
  - 502-producing failure path
  - host/port derivation edge cases
  - logging coverage for decisions and failure reason

## Residual Risk
- Environment-specific routing outside known host/bridge paths may still fail; diagnostics now identify exact attempted targets and error classes deterministically.
