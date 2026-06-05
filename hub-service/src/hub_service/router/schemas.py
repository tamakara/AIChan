from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class UserInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: dict[str, Any]


class MessageHistoryData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]]
    next_before_message_id: int | None


class MessageHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: MessageHistoryData


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
    """agent-service 返回的已解析 OneBot v11 回复。"""

    model_config = ConfigDict(extra="forbid")

    reply: str | list[dict[str, Any]]
    auto_escape: bool = False
