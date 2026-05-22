from __future__ import annotations

from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from ..router.schemas import ChatMessage


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


def render_messages_xml(messages: list[ChatMessage]) -> str:
    # 会话级身份信息统一放在 session_start，不在 message 片段重复，避免模型上下文出现双重事实源。
    return "".join(
        build_message_tag(
            user_id=message.user_id,
            event_time=message.event_time,
            content=message.content,
        )
        for message in messages
    )


def build_message_tag(*, user_id: str, event_time: str, content: str) -> str:
    return (
        f'<message user_id="{_escape_attr(user_id)}" '
        f'event_time="{_escape_attr(event_time)}">'
        f"{_escape_text(content)}"
        "</message>"
    )


def _escape_attr(value: str) -> str:
    return escape(value, entities={'"': "&quot;"})


def _escape_text(value: str) -> str:
    return escape(value)
