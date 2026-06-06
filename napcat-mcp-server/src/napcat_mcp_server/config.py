from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH = Path.cwd() / "napcat-mcp-server" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt


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


class McpSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: StrictStr
    timeout_seconds: float

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        frozen=True,
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
    )

    server: ServerSettings
    napcat: NapcatSettings
    mcp: McpSettings

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
