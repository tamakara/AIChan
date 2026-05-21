from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from ..router.schemas import ChatMessage


def render_messages_xml(metadata: dict[str, Any], messages: list[ChatMessage]) -> str:
    # XML 统一在服务端构建，确保 LLM 看到的是稳定结构而不是调用方拼接的半结构化文本。
    xml_parts = [f"<chat_messages{_build_root_attrs(metadata)}>"]
    for message in messages:
        xml_parts.append(
            (
                f'<message user_id="{_escape_attr(message.user_id)}" '
                f'event_time="{_escape_attr(message.event_time)}">'
                f"{_escape_text(message.content)}"
                "</message>"
            )
        )
    xml_parts.append("</chat_messages>")
    return "".join(xml_parts)


def _escape_attr(value: str) -> str:
    return escape(value, entities={'"': "&quot;"})


def _escape_text(value: str) -> str:
    return escape(value)


def _build_root_attrs(metadata: dict[str, Any]) -> str:
    attrs: list[str] = []
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            continue
        if value is None:
            continue
        attrs.append(f' {_escape_attr(key)}="{_escape_attr(str(value))}"')
    return "".join(attrs)
