from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    metadata: dict[str, Any]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    batch: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """agent 返回已解析的 OneBot v11 回复，由 hub-service 直接投递。"""

    model_config = ConfigDict(extra="forbid")

    reply: str | list[dict[str, Any]]
    auto_escape: bool = False


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
