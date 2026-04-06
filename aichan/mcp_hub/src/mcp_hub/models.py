"""
MCP Hub 领域模型定义。

当前仅保留运行时唤醒信号模型，连接配置改由 MCPManager
直接接收 URL 列表并在连接时动态解析服务信息。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class WakeupSignal:
    """
    MCP 通知转换后的统一唤醒信号。

    字段说明：
    - server_name: 来源 MCP Server 别名；
    - channel: 通道名；
    - reason: 唤醒原因（当前约定为 new_message）；
    - received_at: Hub 接收事件的 UTC ISO 时间；
    - raw_params: 原始通知参数，便于排障审计。
    """

    server_name: str
    channel: str
    reason: str
    received_at: str
    raw_params: dict[str, Any]

    @classmethod
    def build(
        cls,
        *,
        server_name: str,
        channel: str,
        reason: str,
        raw_params: dict[str, Any],
    ) -> "WakeupSignal":
        """创建包含当前 UTC 时间戳的 WakeupSignal。"""
        return cls(
            server_name=server_name,
            channel=channel,
            reason=reason,
            received_at=datetime.now(timezone.utc).isoformat(),
            raw_params=raw_params,
        )
