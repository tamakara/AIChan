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
  session_whitelist:
    - type: private
      id: 1
      enabled: true
napcat:
  ws_action_timeout_seconds: 5
file_service:
  base_url: http://file-service:8040
  timeout_seconds: 25
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("HUB__AGENT_URL", "http://agent-env:8000")
    monkeypatch.setenv("HUB__DEBOUNCE_SECONDS", "3.5")
    monkeypatch.setenv(
        "HUB__SESSION_WHITELIST",
        '[{"type":"group","id":20001,"enabled":true,"require_mention":true,"blocked_user_ids":[2041214552]}]',
    )
    monkeypatch.setenv("NAPCAT__WS_ACTION_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("FILE_SERVICE__BASE_URL", "http://file-env:8040")
    monkeypatch.setenv("FILE_SERVICE__TIMEOUT_SECONDS", "9")

    settings = Settings(_env_file=None)

    assert settings.hub.agent_url == "http://agent-env:8000"
    assert settings.hub.debounce_seconds == 3.5
    assert len(settings.hub.session_whitelist) == 1
    assert settings.hub.session_whitelist[0].type == "group"
    assert settings.hub.session_whitelist[0].id == 20001
    assert settings.hub.session_whitelist[0].session_id == "group_20001"
    assert settings.hub.session_whitelist[0].require_mention is True
    assert settings.hub.session_whitelist[0].blocked_user_ids == (2041214552,)
    assert settings.napcat.ws_action_timeout_seconds == 7.0
    assert settings.file_service.base_url == "http://file-env:8040"
    assert settings.file_service.timeout_seconds == 9.0
