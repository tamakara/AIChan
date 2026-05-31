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
    model_config = ConfigDict(extra="forbid")

    batch: str
