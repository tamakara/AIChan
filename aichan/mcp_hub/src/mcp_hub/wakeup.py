from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core.logger import logger


@dataclass(frozen=True, slots=True)
class WakeupSignal:
    """
    MCP 资源更新信号快照。

    字段说明：
    - server_name: 来源 MCP Server 别名；
    - resource_uri: 资源 URI；
    - received_at: Hub 接收信号的 UTC ISO 时间。
    """

    server_name: str
    resource_uri: str
    received_at: str

    @classmethod
    def build(
        cls,
        *,
        server_name: str,
        resource_uri: str,
    ) -> "WakeupSignal":
        return cls(
            server_name=server_name,
            resource_uri=resource_uri,
            received_at=datetime.now(timezone.utc).isoformat(),
        )


class WakeupEventBus:
    """
    管理资源更新唤醒事件与最近信号快照。

    说明：
    - `_event` 用于跨组件通知“有新唤醒到达”；
    - `_pending_duplicate_count` 记录 event 已置位期间被合并的重复信号数；
    - `_last_wakeup_signal` 用于健康检查与排障观测。
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._pending_duplicate_count = 0
        self._last_wakeup_signal: WakeupSignal | None = None

    async def handle_resource_updated(
        self,
        server_name: str,
        resource_uri: str,
    ) -> None:
        """
        处理 `notifications/resources/updated` 信号并更新总线状态。

        处理策略：
        - signal 只表示“有更新”，不承载业务数据；
        - 当 event 已置位时执行 debounce：仅累计重复次数。
        """
        clean_uri = resource_uri.strip()
        if not clean_uri:
            logger.warning(
                "⚠️ [MCPHub] 忽略空资源更新信号，server='{}'",
                server_name,
            )
            return

        self._last_wakeup_signal = WakeupSignal.build(
            server_name=server_name,
            resource_uri=clean_uri,
        )

        if self._event.is_set():
            self._pending_duplicate_count += 1
            logger.info(
                "🔁 [MCPHub] 收到重复资源信号并已合并，server='{}'，uri='{}'，pending_duplicates={}",
                server_name,
                clean_uri,
                self._pending_duplicate_count,
            )
            return

        self._event.set()
        logger.info(
            "🔔 [MCPHub] 收到资源更新信号并触发唤醒，server='{}'，uri='{}'",
            server_name,
            clean_uri,
        )

    async def wait(self) -> None:
        await self._event.wait()

    def clear(self) -> None:
        pending_duplicates = self._pending_duplicate_count
        self._event.clear()
        self._pending_duplicate_count = 0
        logger.info(
            "🧹 [MCPHub] 唤醒事件已消费并清理，coalesced_duplicates={}",
            pending_duplicates,
        )

    def get_event(self) -> asyncio.Event:
        return self._event

    def get_last_signal(self) -> WakeupSignal | None:
        return self._last_wakeup_signal

    def get_last_snapshot(self) -> dict[str, Any] | None:
        signal = self.get_last_signal()
        if signal is None:
            return None
        return {
            "server_name": signal.server_name,
            "resource_uri": signal.resource_uri,
            "received_at": signal.received_at,
            "pending_duplicate_count": self._pending_duplicate_count,
        }

    def reset(self) -> None:
        self._event = asyncio.Event()
        self._pending_duplicate_count = 0
        self._last_wakeup_signal = None

