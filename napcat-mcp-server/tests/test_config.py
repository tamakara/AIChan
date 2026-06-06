import napcat_mcp_server.config as app_config_module
import napcat_mcp_server.mcp.config as mcp_config_module
from napcat_mcp_server.config import Settings as AppSettings
from napcat_mcp_server.mcp.config import Settings as McpOnlySettings


def test_app_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(app_config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("NAPCAT__WS_ACTION_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("MCP__BASE_URL", "http://hub-env:8020")
    monkeypatch.setenv("MCP__TIMEOUT_SECONDS", "11")

    settings = AppSettings(_env_file=None)

    assert settings.napcat.ws_action_timeout_seconds == 9.0
    assert settings.mcp.base_url == "http://hub-env:8020"
    assert settings.mcp.timeout_seconds == 11.0


def test_mcp_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(mcp_config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("MCP__BASE_URL", "http://hub-env:8020")
    monkeypatch.setenv("MCP__TIMEOUT_SECONDS", "12")

    settings = McpOnlySettings(_env_file=None)

    assert settings.mcp.base_url == "http://hub-env:8020"
    assert settings.mcp.timeout_seconds == 12.0


def _write_config(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8030
napcat:
  ws_action_timeout_seconds: 5
mcp:
  base_url: http://hub-service:8020
  timeout_seconds: 5
""",
        encoding="utf-8",
    )
    return config_path
