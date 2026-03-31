from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

GatewayType = Literal["channel", "tool"]


@dataclass(slots=True, frozen=True)
class GatewayConfig:
    """注册中心内部统一网关配置对象。"""

    name: str
    gateway_type: GatewayType
    base_url: str
    openapi_path: str
    sse_path: str | None


class GatewayRegisterRequest(BaseModel):
    """网关注册请求体。"""

    name: str = Field(..., min_length=1, max_length=100)
    type: GatewayType
    base_url: AnyHttpUrl | str
    openapi_path: str | None = None
    sse_path: str | None = None
