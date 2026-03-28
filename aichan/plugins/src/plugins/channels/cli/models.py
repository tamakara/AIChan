from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DEFAULT_CLI_CHANNEL_NAME: str = "cli"
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
