import tool_mcp_server.config as app_config_module
import tool_mcp_server.mcp.config as mcp_config_module
from tool_mcp_server.config import Settings as AppSettings
from tool_mcp_server.mcp.config import Settings as McpOnlySettings


def test_app_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(app_config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("MCP__BASE_URL", "http://hub-env:8020")
    monkeypatch.setenv("MCP__TIMEOUT_SECONDS", "11")
    monkeypatch.setenv("VISION__MODEL", "vision-env")
    monkeypatch.setenv("VISION__TIMEOUT_SECONDS", "12")

    settings = AppSettings(_env_file=None)

    assert settings.mcp.base_url == "http://hub-env:8020"
    assert settings.mcp.timeout_seconds == 11.0
    assert settings.vision.model == "vision-env"
    assert settings.vision.timeout_seconds == 12.0


def test_mcp_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setattr(mcp_config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("MCP__BASE_URL", "http://hub-env:8020")
    monkeypatch.setenv("MCP__TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("VISION__OPENAI_API_KEY", "vision-key")

    settings = McpOnlySettings(_env_file=None)

    assert settings.mcp.base_url == "http://hub-env:8020"
    assert settings.mcp.timeout_seconds == 12.0
    assert settings.vision.openai_api_key == "vision-key"


def _write_config(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8030
mcp:
  base_url: http://hub-service:8020
  timeout_seconds: 5
vision:
  openai_base_url: https://example.test/v1
  openai_api_key: key
  model: vision-model
  timeout_seconds: 30
""",
        encoding="utf-8",
    )
    return config_path
