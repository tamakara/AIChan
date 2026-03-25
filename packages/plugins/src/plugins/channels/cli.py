from __future__ import annotations

from typing import Literal, cast

from core.entities import ChannelMessage
from plugins.base import ChannelPlugin


class CLIChannelPlugin(ChannelPlugin):
    """CLI 通道插件：维护终端会话消息列表。"""

    def __init__(self, name: str = "cli") -> None:
        super().__init__(name=name)
        self._messages: list[ChannelMessage] = []
        self._next_message_id = 1

    def list_messages(self, since_id: int = 0) -> list[ChannelMessage]:
        """返回指定消息 ID 之后的所有通道消息。"""
        return [msg for msg in self._messages if msg.message_id > since_id]

    def send_message(self, role: str, content: str) -> ChannelMessage:
        """向通道写入一条消息。"""
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("content 不能为空")

        if role not in {"user", "assistant", "system"}:
            raise ValueError(f"不支持的 role: {role}")
        normalized_role = cast(Literal["user", "assistant", "system"], role)

        message = ChannelMessage(
            message_id=self._next_message_id,
            channel=self.name,
            role=normalized_role,
            content=clean_content,
        )
        self._messages.append(message)
        self._next_message_id += 1
        return message
