from pydantic import ValidationError

import agent_service.config as config_module
from agent_service.config import LangfuseSettings, Settings
from agent_service.services.observability import NoopObservability, create_observability


def _base_settings_payload() -> dict:
    return {
        "server": {"host": "0.0.0.0", "port": 8000},
        "agent": {
            "model": "gpt-4.1-mini",
            "max_turns": 5,
            "temperature": 0.3,
            "openai_api_key": "k",
            "openai_base_url": "https://example.com/v1",
            "llm_timeout": 30.0,
            "llm_max_retries": 0,
            "mcp_sse_url": "http://mcp:9000/sse",
            "mcp_auth_token": "",
            "langfuse": {
                "enabled": False,
                "host": "https://cloud.langfuse.com",
                "public_key": "",
                "secret_key": "",
                "flush_at": 16,
                "flush_interval": 0.5,
                "request_timeout": 5.0,
            },
        },
    }


def test_settings_accept_langfuse_config() -> None:
    settings = Settings.model_validate(_base_settings_payload())

    assert settings.agent.langfuse.enabled is False
    assert settings.agent.langfuse.flush_at == 16


def test_settings_reject_missing_langfuse_required_field() -> None:
    payload = _base_settings_payload()
    payload["agent"]["langfuse"].pop("secret_key")

    try:
        LangfuseSettings.model_validate(payload["agent"]["langfuse"])
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_create_observability_returns_noop_when_disabled() -> None:
    settings = Settings.model_validate(_base_settings_payload())

    observability = create_observability(settings.agent.langfuse)

    assert isinstance(observability, NoopObservability)


def test_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8000
agent:
  model: ""
  max_turns: 5
  temperature: 0.3
  openai_api_key: ""
  openai_base_url: https://yaml.example/v1
  llm_timeout: 30.0
  llm_max_retries: 0
  mcp_sse_url: http://mcp:9000/sse
  mcp_auth_token: ""
  langfuse:
    enabled: true
    host: https://cloud.langfuse.com
    public_key: ""
    secret_key: ""
    flush_at: 16
    flush_interval: 0.5
    request_timeout: 5.0
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("AGENT__MODEL", "env-model")
    monkeypatch.setenv("AGENT__OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("AGENT__OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AGENT__LANGFUSE__HOST", "https://env-langfuse.example")
    monkeypatch.setenv("AGENT__LANGFUSE__PUBLIC_KEY", "env-public")
    monkeypatch.setenv("AGENT__LANGFUSE__SECRET_KEY", "env-secret")

    settings = Settings(_env_file=None)

    assert settings.agent.model == "env-model"
    assert settings.agent.openai_api_key == "env-key"
    assert settings.agent.openai_base_url == "https://env.example/v1"
    assert settings.agent.langfuse.host == "https://env-langfuse.example"
    assert settings.agent.langfuse.public_key == "env-public"
    assert settings.agent.langfuse.secret_key == "env-secret"


def test_settings_reject_empty_model() -> None:
    payload = _base_settings_payload()
    payload["agent"]["model"] = ""

    try:
        Settings.model_validate(payload)
        assert False, "expected ValidationError"
    except ValidationError as exc:
        assert "AGENT__MODEL" in str(exc)


def test_settings_reject_empty_openai_api_key() -> None:
    payload = _base_settings_payload()
    payload["agent"]["openai_api_key"] = ""

    try:
        Settings.model_validate(payload)
        assert False, "expected ValidationError"
    except ValidationError as exc:
        assert "AGENT__OPENAI_API_KEY" in str(exc)


def test_settings_rejects_enabled_langfuse_without_credentials() -> None:
    payload = _base_settings_payload()
    payload["agent"]["langfuse"]["enabled"] = True
    payload["agent"]["langfuse"]["public_key"] = ""
    payload["agent"]["langfuse"]["secret_key"] = ""

    try:
        Settings.model_validate(payload)
        assert False, "expected ValueError"
    except ValidationError as exc:
        assert "AGENT__LANGFUSE__PUBLIC_KEY" in str(exc)
