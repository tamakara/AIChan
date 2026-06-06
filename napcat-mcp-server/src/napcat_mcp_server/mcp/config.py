from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictStr, ValidationError, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH = Path.cwd() / "napcat-mcp-server" / "config.yml"


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
