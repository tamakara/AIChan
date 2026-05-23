from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

def build_session_start_tag(agent_id: str, metadata: dict[str, Any]) -> str:
    session_id = metadata.get("session_id")
    if isinstance(session_id, str) and session_id:
        return (
            '<session_start '
            f'agent_id="{_escape_attr(agent_id)}" '
            f'session_id="{_escape_attr(session_id)}"'
            ">"
        )
    return f'<session_start agent_id="{_escape_attr(agent_id)}">'


def _escape_attr(value: str) -> str:
    return escape(value, entities={'"': "&quot;"})
