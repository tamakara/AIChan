from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH = Path.cwd() / "hub-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt
    log_level: StrictStr


class HubSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_url: StrictStr
    debounce_seconds: float
    allowed_user_ids: tuple[StrictInt, ...]

    @field_validator("debounce_seconds", mode="before")
    @classmethod
    def _validate_debounce_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _validate_allowed_user_ids(cls, value: Any) -> tuple[int, ...]:
        if isinstance(value, str):
            # pydantic-settings 对复杂环境变量使用 JSON，直接初始化时也沿用同一格式。
            value = json.loads(value)
        if not isinstance(value, (list, tuple)):
            raise TypeError("必须是数组")
        user_ids: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise TypeError("user_id 必须是整数")
            if item < 1:
                raise ValueError("user_id 必须为正整数")
            user_ids.append(item)
        return tuple(user_ids)


class NapcatSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ws_action_timeout_seconds: float

    @field_validator("ws_action_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)


class StorageSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint: StrictStr
    bucket: StrictStr
    access_key: StrictStr
    secret_key: StrictStr
    secure: StrictBool
    download_timeout_seconds: float
    max_object_bytes: StrictInt

    @field_validator("endpoint", "bucket", "access_key", "secret_key")
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

    @field_validator("download_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        if value <= 0:
            raise ValueError("必须大于 0")
        return float(value)

    @field_validator("max_object_bytes", mode="before")
    @classmethod
    def _validate_max_object_bytes(cls, value: Any) -> int:
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
    hub: HubSettings
    napcat: NapcatSettings
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
        # 所有服务统一使用环境变量覆盖 YAML，便于 docker compose 用同一个 .env 管理部署差异。
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
