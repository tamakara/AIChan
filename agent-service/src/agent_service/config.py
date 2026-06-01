from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, ValidationError

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


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: ServerSettings
    agent: AgentSettings


def _load_config() -> dict[str, Any]:
    payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return payload or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data: Mapping[str, Any] = _load_config()
    try:
        # 统一交给 Pydantic 做严格结构校验，避免手写字段检查逻辑散落且难维护。
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {CONFIG_PATH}\n{exc}") from exc
