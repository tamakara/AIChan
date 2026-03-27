from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFAULT_CLI_CHANNEL_NAME: str= "cli"
DEFAULT_CLI_SERVER_BASE_URL: str= "http://127.0.0.1:8765"
DEFAULT_CLI_TIMEOUT_SECONDS: float = 5.0
CLI_CHANNEL_NAME: str = DEFAULT_CLI_CHANNEL_NAME

CLIChannelSender = Literal["ai", "user"]
CLIChannelReader = Literal["ai", "user"]


@dataclass(frozen=True)
class CLIChannelMessage:
    """外部聊天服务返回的消息结构。"""

    message_id: int
    sender: CLIChannelSender
    text: str
    created_at: str


@dataclass(frozen=True)
class CLIChannelUnreadStatus:
    """外部聊天服务返回的未读状态。"""

    ai_unread: bool
    user_unread: bool
