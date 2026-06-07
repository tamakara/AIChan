from functools import lru_cache
from pathlib import Path

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_PATH = Path.cwd() / "agent-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt


class LangfuseSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool
    host: StrictStr
    public_key: StrictStr
    secret_key: StrictStr
    flush_at: StrictInt
    flush_interval: float
    request_timeout: float

    @model_validator(mode="after")
    def _validate_enabled_credentials(self) -> "LangfuseSettings":
        if self.enabled and (not self.public_key or not self.secret_key):
            raise ValueError("启用 Langfuse 时必须配置 AGENT__LANGFUSE__PUBLIC_KEY 和 AGENT__LANGFUSE__SECRET_KEY")
        return self


class AgentSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: StrictStr
    max_turns: StrictInt
    temperature: float

    openai_api_key: StrictStr
    openai_base_url: StrictStr
    mcp_sse_url: StrictStr
    mcp_auth_token: StrictStr
    llm_timeout: float
    llm_max_retries: StrictInt
    langfuse: LangfuseSettings

    @field_validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        if not value:
            raise ValueError("必须配置 AGENT__MODEL")
        return value

    @field_validator("openai_api_key")
    @classmethod
    def _validate_openai_api_key(cls, value: str) -> str:
        if not value:
            raise ValueError("必须配置 AGENT__OPENAI_API_KEY")
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
    agent: AgentSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 让环境变量覆盖 YAML，密钥就不需要写进仓库里的 config.yml。
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
        # 统一交给 Pydantic 做严格结构校验，避免手写字段检查逻辑散落且难维护。
        return Settings()
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {CONFIG_PATH}\n{exc}") from exc
