import file_service.config as config_module
from file_service.config import Settings


def test_settings_loads_yaml_and_environment_overrides(monkeypatch, tmp_path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 8040
  log_level: debug
storage:
  endpoint: minio:9000
  bucket: aichan-files
  access_key: minio_user
  secret_key: minio_password
  secure: false
  database_path: /data/file-service.sqlite3
  download_timeout_seconds: 20
  max_object_bytes: 10485760
  expire_after_seconds: 604800
  cleanup_interval_seconds: 3600
  cleanup_batch_size: 100
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.setenv("STORAGE__BUCKET", "files-env")
    monkeypatch.setenv("STORAGE__DATABASE_PATH", "/tmp/files.sqlite3")
    monkeypatch.setenv("STORAGE__DOWNLOAD_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("STORAGE__EXPIRE_AFTER_SECONDS", "60")
    monkeypatch.setenv("STORAGE__CLEANUP_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("STORAGE__CLEANUP_BATCH_SIZE", "10")

    settings = Settings(_env_file=None)

    assert settings.storage.bucket == "files-env"
    assert settings.storage.database_path == "/tmp/files.sqlite3"
    assert settings.storage.download_timeout_seconds == 9.0
    assert settings.storage.expire_after_seconds == 60
    assert settings.storage.cleanup_interval_seconds == 30.0
    assert settings.storage.cleanup_batch_size == 10
