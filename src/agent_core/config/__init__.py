from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

from agent_core.errors import ConfigError


_SECTION_KEYS = ("identity", "paths", "providers", "mcp", "auth", "logging", "runtime")
RUNTIME_RUN_MODE_DOCKER = "docker"
RUNTIME_RUN_MODE_NATIVE = "native"
RUNTIME_RUN_MODE_AUTO = "auto"
RUNTIME_RUN_MODE_CHOICES = (
    RUNTIME_RUN_MODE_DOCKER,
    RUNTIME_RUN_MODE_NATIVE,
    RUNTIME_RUN_MODE_AUTO,
)
DEFAULT_RUNTIME_RUN_MODE = RUNTIME_RUN_MODE_DOCKER


def _ensure_dict(value: object, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a table/object.")
    return dict(value)


def _ensure_optional_str(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string.")
    return value


def _copy_section_values(raw: object, *, section: str) -> dict[str, Any]:
    return _ensure_dict(raw, label=f"section '{section}'")


@dataclass(frozen=True)
class IdentityConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PathsConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderDefaultsConfig:
    model: str | None = None
    model_provider: str | None = None
    model_reasoning_effort: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvidersConfig:
    defaults: ProviderDefaultsConfig = field(default_factory=ProviderDefaultsConfig)
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class MCPConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LoggingConfig:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeConfig:
    run_mode: str = DEFAULT_RUNTIME_RUN_MODE
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRuntimeConfig:
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    providers: ProvidersConfig = field(default_factory=ProvidersConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | dict[str, Any]) -> "AgentRuntimeConfig":
        if not isinstance(payload, Mapping):
            raise ConfigError("Config payload root must be a table/object.")

        raw = dict(payload)
        missing_sections = [section for section in _SECTION_KEYS if section not in raw]
        if missing_sections:
            raise ConfigError(
                "Config payload missing required sections: " + ", ".join(missing_sections)
            )

        identity = IdentityConfig(values=_copy_section_values(raw.get("identity"), section="identity"))
        paths = PathsConfig(values=_copy_section_values(raw.get("paths"), section="paths"))
        mcp = MCPConfig(values=_copy_section_values(raw.get("mcp"), section="mcp"))
        auth = AuthConfig(values=_copy_section_values(raw.get("auth"), section="auth"))
        logging = LoggingConfig(values=_copy_section_values(raw.get("logging"), section="logging"))
        runtime = _parse_runtime(raw)
        providers = _parse_providers(raw)

        extras = {k: v for k, v in raw.items() if k not in _SECTION_KEYS}
        return cls(
            identity=identity,
            paths=paths,
            providers=providers,
            mcp=mcp,
            auth=auth,
            logging=logging,
            runtime=runtime,
            extras=extras,
        )

    @classmethod
    def from_toml_path(cls, path: str | Path) -> "AgentRuntimeConfig":
        config_path = Path(path)
        try:
            raw = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Unable to read config file {config_path}: {exc}") from exc
        try:
            parsed = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ConfigError("Config payload root must be a table/object.")
        return cls.from_dict(parsed)


def _parse_providers(raw_root: dict[str, Any]) -> ProvidersConfig:
    providers_raw = _ensure_dict(raw_root.get("providers"), label="section 'providers'")
    defaults_raw = _ensure_dict(providers_raw.get("defaults"), label="section 'providers.defaults'")

    defaults = ProviderDefaultsConfig(
        model=_ensure_optional_str(defaults_raw.pop("model", None), label="providers.defaults.model"),
        model_provider=_ensure_optional_str(
            defaults_raw.pop("model_provider", None),
            label="providers.defaults.model_provider",
        ),
        model_reasoning_effort=_ensure_optional_str(
            defaults_raw.pop("model_reasoning_effort", None),
            label="providers.defaults.model_reasoning_effort",
        ),
        extra=defaults_raw,
    )

    entries: dict[str, dict[str, Any]] = {}
    for key, value in providers_raw.items():
        if key == "defaults":
            continue
        entries[key] = _ensure_dict(value, label=f"section 'providers.{key}'")

    return ProvidersConfig(defaults=defaults, entries=entries)


def parse_runtime_run_mode(value: object, *, label: str = "runtime.run_mode") -> str:
    if value is None:
        return DEFAULT_RUNTIME_RUN_MODE
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be one of: {', '.join(RUNTIME_RUN_MODE_CHOICES)}.")
    resolved = value.strip().lower()
    if resolved not in RUNTIME_RUN_MODE_CHOICES:
        raise ConfigError(f"{label} must be one of: {', '.join(RUNTIME_RUN_MODE_CHOICES)}.")
    return resolved


def _parse_runtime(raw_root: dict[str, Any]) -> RuntimeConfig:
    runtime_raw = _ensure_dict(raw_root.get("runtime"), label="section 'runtime'")
    run_mode = parse_runtime_run_mode(runtime_raw.pop("run_mode", None))
    return RuntimeConfig(run_mode=run_mode, values=runtime_raw)


def load_agent_runtime_config(path: str | Path) -> AgentRuntimeConfig:
    return AgentRuntimeConfig.from_toml_path(path)


def load_agent_runtime_config_dict(payload: Mapping[str, Any] | dict[str, Any]) -> AgentRuntimeConfig:
    return AgentRuntimeConfig.from_dict(payload)


__all__ = [
    "AgentRuntimeConfig",
    "AuthConfig",
    "IdentityConfig",
    "LoggingConfig",
    "MCPConfig",
    "PathsConfig",
    "ProviderDefaultsConfig",
    "ProvidersConfig",
    "RuntimeConfig",
    "DEFAULT_RUNTIME_RUN_MODE",
    "RUNTIME_RUN_MODE_AUTO",
    "RUNTIME_RUN_MODE_CHOICES",
    "RUNTIME_RUN_MODE_DOCKER",
    "RUNTIME_RUN_MODE_NATIVE",
    "load_agent_runtime_config",
    "load_agent_runtime_config_dict",
    "parse_runtime_run_mode",
]
