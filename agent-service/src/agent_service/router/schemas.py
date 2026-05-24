from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    batch: str = Field(min_length=1)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str

