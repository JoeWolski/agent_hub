# Feature Plan: OpenAI Account Login Callback Fix

## Objective
Eliminate `502 Bad Gateway` failures on `/api/settings/auth/openai/account/callback` in Docker-in-Docker and proxied deployments, while adding durable diagnostics that immediately identify callback forwarding failures.

## Scope
- Callback host/port derivation and forwarding path for OpenAI account login.
- Structured/redacted logging across callback resolution, bridge discovery, upstream attempts, and failure categorization.
- Targeted tests for success, failure, and host-derivation edge cases.

## Non-Scope
- Changing OpenAI OAuth semantics.
- Changing login container startup mode or auth provider behavior outside callback forwarding.

## Evidence Plan
- Reproduce baseline 502 with deterministic script (expected failure path).
- Verify post-fix success with deterministic bridge-host fallback script.
- Run targeted pytest suite covering callback routing, failure path, and parsing/logging.
