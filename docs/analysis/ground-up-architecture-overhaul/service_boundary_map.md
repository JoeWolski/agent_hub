# Service Boundary Map (AOH-04)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Landed Service Boundaries
- `SettingsService` extracted to `src/agent_hub/services/settings_service.py`.
- `AuthService` extracted to `src/agent_hub/services/auth_service.py`.

## Domain Ownership (Current)
- `SettingsService`
  - Normalizes settings payload
  - Validates update payload
  - Enforces git identity pairing invariant
- `AuthService`
  - Resolves callback forward candidates and target path
  - Validates callback forwarding contract and diagnostics
- `HubState`
  - Owns project/chat/runtime/credentials/artifacts/autoconfig orchestration
  - Delegates settings read/update normalization to `SettingsService`
  - Delegates auth callback forwarding behavior to `AuthService`

## Route -> Service -> Persistence/Runtime Call Graph (Current)
- `GET /api/settings`
  - route handler -> `HubState.settings_payload()` -> `SettingsService.settings_payload()` -> state store read
- `POST /api/settings`
  - route handler -> `HubState.update_settings()` -> `SettingsService.update_settings()` -> state store write
- `GET /api/settings/auth/openai/account/callback*`
  - route handler -> `HubState.forward_openai_account_callback(...)` -> `AuthService.forward_openai_account_callback(...)` -> forwarded callback payload
