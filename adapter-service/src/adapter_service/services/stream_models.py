from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..router.schemas import FilteredEventPayload


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
    def from_filtered_event(cls, payload: FilteredEventPayload) -> "EventStreamMessage":
        # 事件在网关侧标准化后立即固化为统一消息结构，避免下游再感知 OneBot 差异。
        return cls(
            event_id=str(uuid4()),
            session_id=payload.session_id,
            user_id=payload.user_id,
            content=payload.content,
            source=payload.source,
            message_type=payload.message_type,
            raw_event=payload.raw_event,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "content": self.content,
            "source": self.source,
            "message_type": self.message_type,
            "raw_event": json.dumps(self.raw_event, ensure_ascii=False),
            "created_at": self.created_at,
        }


class ActionPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str = Field(min_length=1)


class ActionStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    session_id: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    payload: ActionPayload
    created_at: str

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> "ActionStreamMessage":
        raw_payload = fields.get("payload", "")
        payload_data = json.loads(raw_payload) if raw_payload else {}
        return cls(
            action_id=fields.get("action_id", ""),
            session_id=fields.get("session_id", ""),
            action_type=fields.get("action_type", ""),
            payload=ActionPayload.model_validate(payload_data),
            created_at=fields.get("created_at", ""),
        )
