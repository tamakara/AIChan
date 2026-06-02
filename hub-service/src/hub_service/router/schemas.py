from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class AgentInboundEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: dict[str, Any]


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    metadata: dict[str, Any]


class SessionChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    batch: str = Field(min_length=1)


class SessionChatResponse(BaseModel):
    """agent-service 返回的 send_msg 参数 — reply 映射到 OneBot v11 的 message。"""

    model_config = ConfigDict(extra="forbid")

    reply: list[dict[str, Any]]
    auto_escape: bool = False
