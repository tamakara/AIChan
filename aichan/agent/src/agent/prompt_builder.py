from __future__ import annotations

from html import escape

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from core.entities import ChannelMessage
from agent.prompt_templates import (
    CONVERSATION_REQUEST_TEMPLATE,
    MESSAGE_TEMPLATE,
    SYSTEM_PROMPT_TEMPLATE,
)

DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE


def build_context_messages(
    old_messages: list[ChannelMessage],
    new_messages: list[ChannelMessage],
) -> list[BaseMessage]:
    """
    将通道消息拆分（旧消息 + 新消息）组装为模型输入。

    输出结构：
    - 1 条固定 SystemMessage（角色边界）
    - 1 条 XML 结构的 HumanMessage（完整对话记录）
    """
    xml_prompt = _build_xml_user_prompt(old_messages=old_messages, new_messages=new_messages)
    return [
        SystemMessage(content=DEFAULT_SYSTEM_PROMPT),
        HumanMessage(content=xml_prompt),
    ]


def _build_xml_user_prompt(
    old_messages: list[ChannelMessage],
    new_messages: list[ChannelMessage],
) -> str:
    old_xml = _render_messages(messages=old_messages)
    new_xml = _render_messages(messages=new_messages)
    return CONVERSATION_REQUEST_TEMPLATE.format(
        old_messages_xml=old_xml,
        new_messages_xml=new_xml,
    )


def _render_messages(
    messages: list[ChannelMessage],
) -> str:
    message_lines: list[str] = []
    for message in messages:
        safe_role = escape(message.role, quote=True)
        safe_content = escape(message.content)
        message_lines.append(
            MESSAGE_TEMPLATE.format(
                message_id=message.message_id,
                role=safe_role,
                content=safe_content,
            )
        )
    return "\n".join(message_lines)
