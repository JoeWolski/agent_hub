# Schema Mapping (AOH-02)

Date: 2026-03-01
Status: Complete (current cycle scope)

## Canonical Runtime Schema
Required top-level sections enforced by `AgentRuntimeConfig`:
- `identity`
- `paths`
- `providers`
- `mcp`
- `auth`
- `logging`
- `runtime`

Behavior implemented in this cycle:
- Missing required sections fail parse with deterministic `ConfigError`.
- Legacy top-level provider backfill (`model`, `model_provider`, `model_reasoning_effort`) is removed from provider defaults.

## Env/Flag To Config Mapping (Current State)
| Runtime concern | Canonical config field(s) | Explicit override(s) still active | Current state |
|---|---|---|---|
| Runtime UID/GID | `identity.uid`, `identity.gid` | `--local-uid`, `--local-gid`, `AGENT_HUB_HOST_UID`, `AGENT_HUB_HOST_GID` | Config-first in Hub and CLI when flags absent |
| Runtime username | `identity.username` | `--local-user`, `AGENT_HUB_HOST_USER` | Config-first in Hub and CLI when flag absent |
| Hub log level | `logging.level` | `--log-level`, `AGENT_HUB_LOG_LEVEL` | Config-first when flag absent |
| Default provider model | `providers.defaults.model`, `providers.defaults.model_provider`, `providers.<agent>.model` | provider CLI args (`--model`) | Config defaults applied when explicit model arg absent |
| Shared prompt context controls | `runtime.project_doc_*` | none | Parsed from canonical runtime config in CLI |
| Runtime run mode | `runtime.run_mode` | `--run-mode` | Canonical run-mode contract enforced (`docker`/`native`/`auto`) with hard-fail requirements |
| Config file path | n/a (startup input) | `--config-file` | Explicit flag now fail-fast when path is missing |
| System prompt file path | n/a (startup input) | `--system-prompt-file` | Explicit flag now fail-fast when path is missing |

## Override Precedence Contract
- Explicit CLI flag/argument override
- Canonical config field
- Explicit environment override (where supported)
- Deterministic static default
