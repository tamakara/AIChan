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

CONFIG_PATH = Path.cwd() / "memory-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt
    log_level: StrictStr


class MemorySettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    root_dir: StrictStr
    model: StrictStr
    openai_api_key: StrictStr
    openai_base_url: StrictStr
    llm_timeout: float
    llm_max_retries: StrictInt
    session_max_lines: StrictInt

    @field_validator("root_dir", "model", "openai_api_key", "openai_base_url")
    @classmethod
    def _validate_required_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("不能为空")
        return value

    @field_validator("llm_timeout", mode="before")
    @classmethod
    def _validate_timeout(cls, value: Any) -> float:
        if isinstance(value, str):
            try:
                value = float(value)
            except ValueError as exc:
                raise TypeError("必须是数字") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        if value <= 0:
            raise ValueError("必须大于 0")
        return float(value)

    @field_validator("llm_max_retries", mode="before")
    @classmethod
    def _validate_retries(cls, value: Any) -> int:
        if isinstance(value, str):
            try:
                value = int(value)
            except ValueError as exc:
                raise TypeError("必须是整数") from exc
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("必须是整数")
        if value < 0:
            raise ValueError("不能小于 0")
        return value

    @field_validator("session_max_lines", mode="before")
    @classmethod
    def _validate_session_max_lines(cls, value: Any) -> int:
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
    memory: MemorySettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # memory-service 是会话记忆文件的唯一拥有者，配置键以当前服务语义为准，不保留旧别名。
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
