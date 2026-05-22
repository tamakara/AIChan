from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError, field_validator
import yaml

CONFIG_PATH = Path.cwd() / "hub-service" / "config.yml"


class ServerSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt
    log_level: StrictStr


class HubSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agent_url: StrictStr
    debounce_seconds: float
    max_wait_seconds: float = 12.0

    @field_validator("debounce_seconds", mode="before")
    @classmethod
    def _validate_debounce_seconds(cls, value: Any) -> float:
        # 防抖窗口控制触发节奏，必须是显式数值避免出现隐式类型导致策略失真。
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)

    @field_validator("max_wait_seconds", mode="before")
    @classmethod
    def _validate_positive_seconds(cls, value: Any) -> float:
        # 总等待上限直接决定强制发送边界，必须是正数才能形成明确时序约束。
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        seconds = float(value)
        if seconds <= 0:
            raise ValueError("必须大于 0")
        return seconds


class RedisSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    host: StrictStr
    port: StrictInt
    db: StrictInt
    password: StrictStr
    events_stream: StrictStr
    events_group: StrictStr
    events_consumer: StrictStr
    events_block_ms: StrictInt
    actions_stream: StrictStr


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: ServerSettings
    hub: HubSettings
    redis: RedisSettings


def _load_config() -> dict[str, Any]:
    try:
        payload = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"配置文件格式错误: {CONFIG_PATH}") from exc

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件顶层必须是 mapping: {CONFIG_PATH}")
    return payload


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data: Mapping[str, Any] = _load_config()
    try:
        # 使用统一模型做强约束，确保缺字段、错类型、未知字段在启动阶段一次性暴露。
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {CONFIG_PATH}\n{exc}") from exc
