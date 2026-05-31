from pydantic import ValidationError

from agent_service.config import Settings
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
            "openai_timeout": 30.0,
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
        Settings.model_validate(payload)
        assert False, "expected ValidationError"
    except ValidationError:
        pass


def test_create_observability_returns_noop_when_disabled() -> None:
    settings = Settings.model_validate(_base_settings_payload())

    observability = create_observability(settings.agent.langfuse)

    assert isinstance(observability, NoopObservability)
