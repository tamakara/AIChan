from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    session_id: str
    user_id: str
    content: str
    source: Literal["qq"]
    message_type: Literal["group", "private"]
    raw_event: dict[str, Any]
    created_at: str

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> "EventStreamMessage":
        raw_event = json.loads(fields.get("raw_event", "{}"))
        return cls(
            event_id=fields.get("event_id", ""),
            session_id=fields.get("session_id", ""),
            user_id=fields.get("user_id", ""),
            content=fields.get("content", ""),
            source=fields.get("source", "qq"),  # type: ignore[arg-type]
            message_type=fields.get("message_type", "private"),  # type: ignore[arg-type]
            raw_event=raw_event if isinstance(raw_event, dict) else {},
            created_at=fields.get("created_at", ""),
        )


class SendMessageActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)


class ActionStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    session_id: str
    action_type: Literal["send_message"]
    payload: SendMessageActionPayload
    created_at: str

    @classmethod
    def for_send_message(cls, session_id: str, content: str) -> "ActionStreamMessage":
        return cls(
            action_id=str(uuid4()),
            session_id=session_id,
            action_type="send_message",
            payload=SendMessageActionPayload(content=content),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "action_type": self.action_type,
            "payload": json.dumps(self.payload.model_dump(), ensure_ascii=False),
            "created_at": self.created_at,
        }
