from __future__ import annotations

from pathlib import Path

import pytest

from agent_core import ConfigError
from agent_core.config import AgentRuntimeConfig, load_agent_runtime_config, load_agent_runtime_config_dict


def test_agent_runtime_config_defaults() -> None:
    config = load_agent_runtime_config_dict({})

    assert isinstance(config, AgentRuntimeConfig)
    assert config.identity.values == {}
    assert config.paths.values == {}
    assert config.providers.defaults.model is None
    assert config.providers.defaults.model_provider is None
    assert config.providers.defaults.model_reasoning_effort is None
    assert config.providers.entries == {}
    assert config.mcp.values == {}
    assert config.auth.values == {}
    assert config.logging.values == {}
    assert config.runtime.values == {}
    assert config.extras == {}


def test_agent_runtime_config_section_parsing() -> None:
    config = load_agent_runtime_config_dict(
        {
            "identity": {"name": "agent"},
            "paths": {"workspace": "/tmp/work"},
            "providers": {
                "defaults": {"model": "gpt-5", "model_provider": "openai", "temperature": 0.2},
                "openai": {"base_url": "https://api.openai.com"},
            },
            "mcp": {"enabled": True},
            "auth": {"mode": "api_key"},
            "logging": {"level": "info"},
            "runtime": {"parallelism": 4},
            "custom_key": "value",
        }
    )

    assert config.identity.values == {"name": "agent"}
    assert config.paths.values == {"workspace": "/tmp/work"}
    assert config.providers.defaults.model == "gpt-5"
    assert config.providers.defaults.model_provider == "openai"
    assert config.providers.defaults.extra == {"temperature": 0.2}
    assert config.providers.entries == {"openai": {"base_url": "https://api.openai.com"}}
    assert config.mcp.values == {"enabled": True}
    assert config.auth.values == {"mode": "api_key"}
    assert config.logging.values == {"level": "info"}
    assert config.runtime.values == {"parallelism": 4}
    assert config.extras == {"custom_key": "value"}


def test_agent_runtime_config_legacy_top_level_provider_defaults_compat() -> None:
    config = load_agent_runtime_config_dict(
        {
            "model": "gpt-4.1-mini",
            "model_provider": "openai",
            "providers": {"defaults": {"model_reasoning_effort": "medium"}},
        }
    )

    assert config.providers.defaults.model == "gpt-4.1-mini"
    assert config.providers.defaults.model_provider == "openai"
    assert config.providers.defaults.model_reasoning_effort == "medium"


def test_agent_runtime_config_invalid_toml_and_field_type_raises_config_error(tmp_path: Path) -> None:
    invalid_toml_path = tmp_path / "invalid.toml"
    invalid_toml_path.write_text("model = ", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_agent_runtime_config(invalid_toml_path)

    with pytest.raises(ConfigError):
        load_agent_runtime_config_dict({"providers": {"defaults": {"model": 123}}})
