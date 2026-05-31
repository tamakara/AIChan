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
    model_config = ConfigDict(extra="forbid")

    batch: str


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
