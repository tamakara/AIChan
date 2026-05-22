from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class AgentInboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    event_time: str = Field(min_length=1)


class AgentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    metadata: dict[str, Any]


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    messages: list[AgentInboundMessage] = Field(min_length=1)


class AgentChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str
