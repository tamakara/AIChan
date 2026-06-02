from typing import Annotated, Any

from nonebot.adapters.onebot.v11 import Message
from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _serialize_message(msg: Message) -> list[dict[str, Any]]:
    """将 nonebot Message 序列化为 OneBot v11 消息段数组。"""
    return [{"type": seg.type, "data": seg.data} for seg in msg]


MessageField = Annotated[
    Message,
    PlainSerializer(_serialize_message, return_type=list[dict[str, Any]]),
]


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
    """OneBot v11 send_msg 参数 — 可直接透传给 NapCat。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    reply: MessageField
    auto_escape: bool = False


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
