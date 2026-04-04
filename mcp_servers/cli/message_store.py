from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Protocol

from .models import CLIChannelIdentity, ChatMessage

"""
消息存储抽象与默认实现。

设计目标：
1. 通过 `ChatStore` 协议定义最小接口，供 HTTP 层与 MCP 层共同依赖；
2. 默认提供内存实现 `AsyncChatStore`，便于本地运行和单进程部署；
3. 后续可无缝替换为 Redis/数据库实现，而无需改动上层路由逻辑。
"""


class ChatStore(Protocol):
    """聊天存储协议。"""

    async def list_messages(self, after_id: int = 0) -> list[ChatMessage]:
        """列出指定 ID 之后的消息快照。"""

    async def wait_for_messages(
        self, after_id: int, timeout_seconds: float
    ) -> list[ChatMessage]:
        """等待新消息（支持超时返回），用于 SSE 长连接增量推送。"""

    async def send_message(self, sender: CLIChannelIdentity, text: str) -> ChatMessage:
        """写入一条消息并返回完整消息对象。"""


class AsyncChatStore:
    """
    基于 AsyncIO 的内存消息存储。

    并发策略：
    - `_lock` 保护消息数组与自增 ID；
    - `_new_message_cond` 用于通知等待中的 SSE 消费者。
    """

    def __init__(self) -> None:
        # 按时间顺序保存全部消息。
        self._messages: list[ChatMessage] = []
        # 自增主键起始值。
        self._next_id = 1
        # 互斥锁：保护共享状态。
        self._lock = asyncio.Lock()
        # 条件变量：新消息到达时唤醒等待方。
        self._new_message_cond = asyncio.Condition(self._lock)

    async def list_messages(self, after_id: int = 0) -> list[ChatMessage]:
        """返回 `after_id` 之后的消息列表。"""
        async with self._lock:
            return [msg for msg in self._messages if msg.id > after_id]

    async def wait_for_messages(
        self, after_id: int, timeout_seconds: float
    ) -> list[ChatMessage]:
        """
        等待指定游标之后的新消息。

        行为说明：
        1. 若当前已有新消息，立即返回；
        2. 若没有新消息，则阻塞等待通知或超时；
        3. 超时后返回空列表，交由上层发送 keep-alive。
        """
        async with self._new_message_cond:
            messages = [msg for msg in self._messages if msg.id > after_id]
            if not messages:
                try:
                    await asyncio.wait_for(
                        self._new_message_cond.wait(), timeout=timeout_seconds
                    )
                except asyncio.TimeoutError:
                    pass
                messages = [msg for msg in self._messages if msg.id > after_id]
            return messages

    async def send_message(self, sender: CLIChannelIdentity, text: str) -> ChatMessage:
        """
        写入一条消息并广播通知。

        会先做空白清洗，避免存储无意义消息。
        """
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text 不能为空")
        async with self._lock:
            message = ChatMessage(
                id=self._next_id,
                sender=sender,
                text=clean_text,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._messages.append(message)
            self._next_id += 1
            # 新消息写入完成后唤醒所有等待中的消费者（如 SSE 连接）。
            self._new_message_cond.notify_all()
        return message
