from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class EventStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    session_id: str
    event_xml: str
    raw_event: dict[str, Any]
    created_at: str

    @classmethod
    def from_stream_fields(cls, fields: dict[str, str]) -> "EventStreamMessage":
        raw_event = json.loads(fields.get("raw_event", "{}"))
        return cls(
            event_id=fields.get("event_id", ""),
            session_id=fields.get("session_id", ""),
            event_xml=fields.get("event_xml", ""),
            raw_event=raw_event if isinstance(raw_event, dict) else {},
            created_at=fields.get("created_at", ""),
        )


class ActionStreamMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    session_id: str
    action_xml: str
    created_at: str

    @classmethod
    def for_action_xml(cls, session_id: str, action_xml: str) -> "ActionStreamMessage":
        return cls(
            action_id=str(uuid4()),
            session_id=session_id,
            action_xml=action_xml,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "action_id": self.action_id,
            "session_id": self.session_id,
            "action_xml": self.action_xml,
            "created_at": self.created_at,
        }
