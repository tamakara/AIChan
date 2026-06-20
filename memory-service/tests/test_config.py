import pytest
from pydantic import ValidationError

import memory_service.config as config_module
from memory_service.config import Settings


def test_settings_loads_session_max_lines_from_yaml_and_env(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8050
  log_level: info
memory:
  root_dir: /data/memories
  model: model-name
  openai_api_key: key
  openai_base_url: https://example.test/v1
  llm_timeout: 30
  llm_max_retries: 3
  session_max_lines: 500
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("MEMORY__SESSION_MAX_LINES", "123")

    settings = Settings(_env_file=None)

    assert settings.memory.session_max_lines == 123


def test_settings_rejects_invalid_session_max_lines(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8050
  log_level: info
memory:
  root_dir: /data/memories
  model: model-name
  openai_api_key: key
  openai_base_url: https://example.test/v1
  llm_timeout: 30
  llm_max_retries: 3
  session_max_lines: 0
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
