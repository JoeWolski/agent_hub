# Ground-Up Architecture Overhaul (PR-236)

## Current Progress (Updated 2026-03-02)
This branch is in active completion toward the overhaul spec with additional gap-closure work now landed beyond the previous status update.

## Newly Closed Gaps In This Update
- Enforced strict API JSON-shape validation for `POST /api/chats` and `PATCH /api/chats/{chat_id}` to prevent non-object payload 500s (now deterministic 400s).
- Expanded strict legacy-arg rejection coverage (`codex_args`) for create/patch chat routes.
- Added migration hardening tests for legacy state precedence and invalid persisted `agent_type` fail-fast behavior.
- Fixed CLI explicit-path strictness detection by using Click parameter sources instead of `sys.argv` inference under test/runtime wrappers.
- Tightened callback forwarding host resolution policy by removing request-derived host fallbacks.
- Removed container-loopback callback fallback from auth forwarding path; forwarding now stays on resolved host policy path and fails deterministically when unreachable.
- Switched hub supplemental GID parsing to strict mode (`invalid token` now fails).
- Removed cwd fallback probing from shared config/system-prompt discovery helpers; canonical repo-path resolution is now deterministic.
- Fixed strict git identity control-char validation to inspect raw input before whitespace compaction.

## Newly Added/Updated Test Coverage
- Route tests for non-object JSON payloads, invalid agent types, missing required fields, and empty patch payloads.
- Route tests for strict parsing in project chat start and settings patch payload shape.
- Settings validation tests for invalid default agent type, control characters, and length overflow.
- Capability runtime-image strict provider rejection test.
- Callback forwarding tests updated to enforce no request-host/container-loopback fallback behavior.
- Core shared-path tests updated for canonical path policy.

## Validation Evidence (Latest Runs)
- `uv run --python 3.13 -m pytest tests/test_agent_core_shared.py -q`: PASS (`10 passed`)
- `uv run --python 3.13 -m pytest tests/test_hub_and_cli.py -q`: PASS (`376 passed, 3 subtests passed`)
- `uv run --python 3.13 -m pytest tests/integration/test_hub_chat_lifecycle_api.py -q`: PASS (`6 passed`)
- Targeted callback-forward/route/migration/settings subsets: PASS

## Remaining Work In Progress
- Complete deeper architectural extraction still centered in `HubState`/`server.py` to reach final decomposition target (`api/runtime/store/integrations` boundaries).
- Complete runtime identity contract centralization and typed error taxonomy wiring across remaining runtime paths.
- Continue iterative re-audit and closure until no implementation gaps remain against overhaul spec.

## Constraint
Feature docs and acceptance criteria are not being downscoped; implementation is being brought up to spec.
