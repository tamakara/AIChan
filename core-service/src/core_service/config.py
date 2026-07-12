from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_PATH = Path.cwd() / "core-service" / "config.yml"


class LangfuseSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = True
    host: str = ""
    public_key: str = ""
    secret_key: str = ""
    flush_at: int = 16
    flush_interval: float = 0.5
    request_timeout: float = 15.0

    @model_validator(mode="after")
    def validate_credentials(self) -> "LangfuseSettings":
        if self.enabled and (not self.public_key or not self.secret_key):
            raise ValueError("启用 Langfuse 时必须配置密钥")
        return self


class CoreSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    host: str = "0.0.0.0"
    port: int = 8020
    log_level: str = "info"
    model: str
    openai_api_key: str
    openai_base_url: str
    temperature: float = 0.8
    max_turns: int = 20
    llm_timeout: float = 30.0
    llm_max_retries: int = 3
    mcp_sse_url: str = "http://mcp-gateway:9000/sse"
    mcp_auth_token: str = ""
    memory_enabled: bool = True
    memory_base_url: str = "http://memory-service:8050"
    memory_timeout: float = 10.0
    memory_compress_every_n_records: int = 10
    file_service_url: str = "http://file-service:8040"
    debounce_seconds: float = 2.0
    ack_timeout_seconds: float = 10.0
    ack_max_attempts: int = 3
    capability_timeout_seconds: float = 30.0
    adapter_tokens: dict[str, str] = Field(default_factory=dict)
    system_prompt_path: str = "core-service/prompts/system.md"
    skills_root: str = "skills/system"
    max_skill_bytes: int = 65_536
    max_skill_snapshot_bytes: int = 262_144
    max_xml_bytes: int = 262_144
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)

    @field_validator("adapter_tokens", mode="before")
    @classmethod
    def parse_tokens(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_required(self) -> "CoreSettings":
        if not self.model or not self.openai_api_key:
            raise ValueError("CORE__MODEL 和 CORE__OPENAI_API_KEY 必须配置")
        return self


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__")
    core: CoreSettings

    @classmethod
    def settings_customise_sources(cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource, env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource, file_secret_settings: PydanticBaseSettingsSource) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls, yaml_file=CONFIG_PATH, yaml_file_encoding="utf-8"), file_secret_settings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
