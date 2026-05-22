from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from ..router.schemas import ChatMessage


def render_messages_xml(messages: list[ChatMessage]) -> str:
    # 会话级身份信息已在 session_start 注入，消息体只保留 message 片段，
    # 避免同一语义在两处重复声明导致上下文漂移。
    xml_parts: list[str] = []
    for message in messages:
        xml_parts.append(
            (
                f'<message user_id="{_escape_attr(message.user_id)}" '
                f'event_time="{_escape_attr(message.event_time)}">'
                f"{_escape_text(message.content)}"
                "</message>"
            )
        )
    return "".join(xml_parts)


def _escape_attr(value: str) -> str:
    return escape(value, entities={'"': "&quot;"})


def _escape_text(value: str) -> str:
    return escape(value)
