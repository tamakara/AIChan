from __future__ import annotations

import time
from typing import Literal

from core.entities import ChannelMessage
from core.logger import logger
from plugins.base import ChannelPlugin
from plugins.channels.cli.client import CLIMessageServiceClient, CLIMessageServiceError
from plugins.channels.cli.models import (
    CLIChannelMessage,
    CLIChannelSender,
    DEFAULT_CLI_CHANNEL_NAME,
    DEFAULT_CLI_SERVER_BASE_URL,
    DEFAULT_CLI_TIMEOUT_SECONDS,
)


class CLIChannelPlugin(ChannelPlugin):
    """
    CLI 通道插件：对接外部聊天服务并统一转换为 AIChan 内部消息格式。

    约定：
    - 外部协议 sender: ai/user
    - 内部协议 role: assistant/user/system
    """

    def __init__(
        self,
        name: str = DEFAULT_CLI_CHANNEL_NAME,
        server_base_url: str = DEFAULT_CLI_SERVER_BASE_URL,
        timeout_seconds: float = DEFAULT_CLI_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(name=name)
        self._client = CLIMessageServiceClient(
            server_base_url=server_base_url,
            timeout_seconds=timeout_seconds,
        )

    def list_messages(self, since_id: int = 0) -> list[ChannelMessage]:
        started_at = time.perf_counter()
        logger.info(
            "📨 [CLIChannelPlugin] 开始拉取消息，channel='{}'，since_id={}",
            self.name,
            since_id,
        )
        try:
            raw_messages = self._client.list_messages(reader="ai", after_id=since_id)
        except CLIMessageServiceError as exc:
            raise RuntimeError(f"CLI 通道拉取消息失败：{exc}") from exc

        messages = [self._to_channel_message(item) for item in raw_messages]
        latest_message_id = max((item.message_id for item in messages), default=since_id)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "📨 [CLIChannelPlugin] 拉取完成，channel='{}'，count={}，latest_message_id={}，耗时={}ms",
            self.name,
            len(messages),
            latest_message_id,
            elapsed_ms,
        )
        return messages

    def send_message(self, role: str, content: str) -> ChannelMessage:
        started_at = time.perf_counter()
        try:
            sender = self._to_external_sender(role=role)
            logger.info(
                "📤 [CLIChannelPlugin] 开始发送消息，channel='{}'，role='{}'，sender='{}'，content_length={}字符",
                self.name,
                role,
                sender,
                len(content),
            )
            raw_message = self._client.send_message(
                sender=sender,
                text=content,
            )
        except CLIMessageServiceError as exc:
            raise RuntimeError(f"CLI 通道发送消息失败：{exc}") from exc

        message = self._to_channel_message(raw_message)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "📤 [CLIChannelPlugin] 发送完成，channel='{}'，message_id={}，role='{}'，耗时={}ms",
            self.name,
            message.message_id,
            message.role,
            elapsed_ms,
        )
        return message

    def _to_channel_message(self, message: CLIChannelMessage) -> ChannelMessage:
        return ChannelMessage(
            message_id=message.message_id,
            channel=self.name,
            role=self._to_internal_role(sender=message.sender),
            content=message.text,
        )

    def _to_internal_role(self, sender: CLIChannelSender) -> Literal["user", "assistant"]:
        if sender == "user":
            return "user"
        return "assistant"

    def _to_external_sender(self, role: str) -> CLIChannelSender:
        if role == "user":
            return "user"
        if role in {"assistant", "system"}:
            return "ai"
        raise CLIMessageServiceError(f"不支持的内部 role: {role}")
