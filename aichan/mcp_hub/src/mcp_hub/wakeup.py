from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.logger import logger

from .session import AICHAN_WAKEUP_METHOD


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


class WakeupEventBus:
    """
    管理 MCP 唤醒事件与最近一次唤醒信号快照。

    说明：
    - `_event` 用于跨组件通知“有新唤醒到达”；
    - `_last_wakeup_signal` 用于健康检查与排障观测。
    """

    def __init__(self) -> None:
        # 全局唤醒事件：收到任意有效唤醒后置位。
        self._event = asyncio.Event()

        # 最近一次唤醒信号，默认无值。
        self._last_wakeup_signal: WakeupSignal | None = None

    async def handle_wakeup_notification(
        self,
        server_name: str,
        params: dict[str, Any] | None,
    ) -> None:
        """
        处理 wakeup 通知并更新总线状态。

        处理策略：
        - 只要 method 命中 wakeup，就触发 event；
        - channel/reason 缺失时统一填充为 `unknown`。
        """
        # 非 dict 参数统一归一化为空字典，避免后续字段访问报错。
        normalized_params = params if isinstance(params, dict) else {}
        channel = str(normalized_params.get("channel") or "unknown").strip() or "unknown"
        reason = str(normalized_params.get("reason") or "unknown").strip() or "unknown"

        # 构造结构化唤醒信号并保存为“最近一次”快照。
        signal = WakeupSignal.build(
            server_name=server_name,
            channel=channel,
            reason=reason,
            raw_params=normalized_params,
        )
        self._last_wakeup_signal = signal

        # 置位事件，通知等待中的运行时开始处理。
        self._event.set()
        logger.info(
            "🔔 [MCPHub] 收到唤醒通知，method='{}'，server='{}'，channel='{}'，reason='{}'",
            AICHAN_WAKEUP_METHOD,
            server_name,
            channel,
            reason,
        )

    async def wait(self) -> None:
        """等待唤醒事件被置位。"""
        await self._event.wait()

    def clear(self) -> None:
        """清理唤醒事件置位标记。"""
        self._event.clear()

    def get_event(self) -> asyncio.Event:
        """返回内部事件对象（供外部只读观测状态）。"""
        return self._event

    def get_last_signal(self) -> WakeupSignal | None:
        """返回最近一次唤醒信号对象。"""
        return self._last_wakeup_signal

    def get_last_snapshot(self) -> dict[str, Any] | None:
        """返回最近一次唤醒信号的可序列化快照。"""
        signal = self.get_last_signal()
        if signal is None:
            return None
        return {
            "server_name": signal.server_name,
            "channel": signal.channel,
            "reason": signal.reason,
            "received_at": signal.received_at,
        }

    def reset(self) -> None:
        """重置事件与快照，通常在停止阶段调用。"""
        self._event = asyncio.Event()
        self._last_wakeup_signal = None
