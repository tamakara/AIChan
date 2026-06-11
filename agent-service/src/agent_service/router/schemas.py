from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    metadata: dict[str, Any]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    input_xml: str = Field(min_length=1)


class QueueMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_xml: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """agent 返回 AICHAN XML 回复，由 hub-service 转为 QQ 私聊消息。"""

    model_config = ConfigDict(extra="forbid")

    output_xml: str = Field(min_length=1)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
