from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

CONFIG_PATH = Path.cwd() / "skill-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    host: StrictStr
    port: StrictInt


class SkillSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    system_root: StrictStr
    max_skill_bytes: StrictInt
    max_adapter_snapshot_bytes: StrictInt


class Settings(BaseSettings):
    model_config = SettingsConfigDict(frozen=True, extra="ignore", env_file=".env", env_nested_delimiter="__")
    server: ServerSettings
    skills: SkillSettings

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
