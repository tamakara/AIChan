from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..router.schemas import FilteredEventPayload


class EventStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    session_id: str
    event_xml: str
    raw_event: dict[str, Any]
    created_at: str

    @classmethod
    def from_filtered_event(cls, payload: FilteredEventPayload) -> "EventStreamMessage":
        # 事件在网关侧标准化后立即固化为统一消息结构，避免下游再感知 OneBot 差异。
        return cls(
            event_id=str(uuid4()),
            session_id=payload.session_id,
            event_xml=payload.event_xml,
            raw_event=payload.raw_event,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "event_xml": self.event_xml,
            "raw_event": json.dumps(self.raw_event, ensure_ascii=False),
            "created_at": self.created_at,
        }


class ActionStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    session_id: str = Field(min_length=1)
    action_xml: str = Field(min_length=1)
    created_at: str

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> "ActionStreamMessage":
        return cls(
            action_id=fields.get("action_id", ""),
            session_id=fields.get("session_id", ""),
            action_xml=fields.get("action_xml", ""),
            created_at=fields.get("created_at", ""),
        )
