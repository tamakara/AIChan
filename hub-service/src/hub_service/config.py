from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_PATH = Path.cwd() / "hub-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    host: StrictStr
    port: StrictInt
    log_level: StrictStr


class HubSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    agent_url: StrictStr
    file_service_url: StrictStr
    skill_service_url: StrictStr
    debounce_seconds: float
    ack_timeout_seconds: float
    ack_max_attempts: StrictInt
    capability_timeout_seconds: float
    adapter_tokens: dict[str, str]

    @field_validator("adapter_tokens", mode="before")
    @classmethod
    def _parse_tokens(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_file=".env", env_nested_delimiter="__")
    server: ServerSettings
    hub: HubSettings

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, dotenv_settings,
                YamlConfigSettingsSource(settings_cls, yaml_file=CONFIG_PATH, yaml_file_encoding="utf-8"),
                file_secret_settings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
