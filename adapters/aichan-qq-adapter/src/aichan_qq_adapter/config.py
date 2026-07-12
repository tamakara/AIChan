from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_PATH = Path.cwd() / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    host: StrictStr
    port: StrictInt


class SessionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["private", "group"]
    id: StrictInt
    enabled: StrictBool = True
    require_mention: StrictBool = False
    blocked_user_ids: tuple[StrictInt, ...] = ()


class AdapterSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    adapter_id: StrictStr
    instance_id: StrictStr
    hub_ws_url: StrictStr
    hub_http_url: StrictStr
    hub_token: StrictStr
    action_timeout_seconds: float
    ack_timeout_seconds: float
    reconnect_seconds: float
    session_whitelist: tuple[SessionRule, ...]

    @field_validator("session_whitelist", mode="before")
    @classmethod
    def _parse_rules(cls, value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_file=".env", env_nested_delimiter="__")
    server: ServerSettings
    adapter: AdapterSettings

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
