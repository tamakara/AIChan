from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH = Path.cwd() / "file-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt
    log_level: StrictStr


class StorageSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: StrictStr
    bucket: StrictStr
    access_key: StrictStr
    secret_key: StrictStr
    secure: StrictBool
    database_path: StrictStr
    download_timeout_seconds: float
    max_object_bytes: StrictInt
    expire_after_seconds: StrictInt
    cleanup_interval_seconds: float
    cleanup_batch_size: StrictInt

    @field_validator("endpoint", "bucket", "access_key", "secret_key", "database_path")
    @classmethod
    def _validate_required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value

    @field_validator("secure", mode="before")
    @classmethod
    def _validate_secure(cls, value: Any) -> bool:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return value

    @field_validator("download_timeout_seconds", "cleanup_interval_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        if value <= 0:
            raise ValueError("必须大于 0")
        return float(value)

    @field_validator("max_object_bytes", "expire_after_seconds", "cleanup_batch_size", mode="before")
    @classmethod
    def _validate_positive_int(cls, value: Any) -> int:
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError as exc:
                raise TypeError("必须是整数") from exc
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("必须是整数")
        if value < 1:
            raise ValueError("必须大于 0")
        return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    server: ServerSettings
    storage: StorageSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 文件服务是 MinIO/SQLite 的唯一拥有者，部署差异只能通过当前配置键覆盖。
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=CONFIG_PATH, yaml_file_encoding="utf-8"),
            file_secret_settings,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {CONFIG_PATH}\n{exc}") from exc


def _parse_float_env(value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise TypeError("必须是数字") from exc
