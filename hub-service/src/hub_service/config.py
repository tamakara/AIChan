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
    allowed_user_ids: tuple[StrictInt, ...]

    @field_validator("debounce_seconds", mode="before")
    @classmethod
    def _validate_debounce_seconds(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _validate_allowed_user_ids(cls, value: Any) -> tuple[int, ...]:
        if not isinstance(value, (list, tuple)):
            raise TypeError("必须是数组")
        user_ids: list[int] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise TypeError("user_id 必须是整数")
            if item < 1:
                raise ValueError("user_id 必须为正整数")
            user_ids.append(item)
        return tuple(user_ids)


class NapcatSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ws_action_timeout_seconds: float

    @field_validator("ws_action_timeout_seconds", mode="before")
    @classmethod
    def _validate_timeout_seconds(cls, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("必须是数字")
        return float(value)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    server: ServerSettings
    hub: HubSettings
    napcat: NapcatSettings


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
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {CONFIG_PATH}\n{exc}") from exc
