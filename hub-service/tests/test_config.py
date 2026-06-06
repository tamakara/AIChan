import hub_service.config as config_module
from hub_service.config import Settings


def test_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8020
  log_level: debug
hub:
  agent_url: http://agent-service:8000
  debounce_seconds: 2.0
  allowed_user_ids: [1]
napcat:
  ws_action_timeout_seconds: 5
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HUB__AGENT_URL", "http://agent-env:8000")
    monkeypatch.setenv("HUB__DEBOUNCE_SECONDS", "3.5")
    monkeypatch.setenv("HUB__ALLOWED_USER_IDS", "[2041214551,2041214552]")
    monkeypatch.setenv("NAPCAT__WS_ACTION_TIMEOUT_SECONDS", "7")

    settings = Settings(_env_file=None)

    assert settings.hub.agent_url == "http://agent-env:8000"
    assert settings.hub.debounce_seconds == 3.5
    assert settings.hub.allowed_user_ids == (2041214551, 2041214552)
    assert settings.napcat.ws_action_timeout_seconds == 7.0
