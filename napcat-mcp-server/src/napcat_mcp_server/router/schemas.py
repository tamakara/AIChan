from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"


class UserInfoResponse(BaseModel):
    ok: bool
    data: dict[str, Any]


class MessageHistoryData(BaseModel):
    messages: list[dict[str, Any]]
    next_before_message_id: int | None = None


class MessageHistoryResponse(BaseModel):
    ok: bool
    data: MessageHistoryData
