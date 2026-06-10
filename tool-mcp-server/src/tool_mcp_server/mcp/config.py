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

CONFIG_PATH = Path.cwd() / "tool-mcp-server" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt


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


class VisionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    openai_base_url: StrictStr
    openai_api_key: StrictStr
    model: StrictStr
    timeout_seconds: float
    video_frame_count: StrictInt

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, str):
            value = _parse_float_env(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        if value <= 0:
            raise ValueError("必须大于 0")
        return float(value)

    @field_validator("video_frame_count", mode="before")
    @classmethod
    def _validate_video_frame_count(cls, value: Any) -> int:
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError as exc:
                raise TypeError("必须是整数") from exc
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("必须是整数")
        if value < 1 or value > 12:
            raise ValueError("必须在 1 到 12 之间")
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
    mcp: McpSettings
    vision: VisionSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # MCP 命令由 gateway 拉起，也复用同一套 YAML + 环境变量覆盖规则。
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
