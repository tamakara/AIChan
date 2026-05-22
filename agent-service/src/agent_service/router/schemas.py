from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    event_time: str = Field(min_length=1)


class CreateAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateAgentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    metadata: dict[str, Any]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    message_mode: Literal["start", "append"] = "start"


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str

