from __future__ import annotations

import asyncio
import re
from typing import Any

from langchain_core.tools import StructuredTool

from core.logger import logger
from .connections import MCPConnectionPool
from .models import WakeupSignal
from .tool_catalog import MCPToolCatalog
from .tool_executor import MCPToolExecutor
from .wakeup import WakeupEventBus


class MCPManager:
    """
    MCP 多服务连接管理器。

    设计目标：
    1. 统一维护 MCP 会话生命周期；
    2. 动态发现并包装工具；
    3. 以 MCP Custom Notification 触发全局唤醒 Event。
    """

    def __init__(
        self,
        *,
        reconnect_seconds: float,
    ) -> None:
        # 连接池：负责会话生命周期与资源管理。
        self._connections = MCPConnectionPool()

        # 唤醒总线：负责 event 置位与最近唤醒快照。
        self._wakeup_bus = WakeupEventBus()

        # 工具执行器：负责原始工具调用与结果解析。
        self._tool_executor = MCPToolExecutor(
            sessions_provider=lambda: self._connections.sessions
        )

        # 工具目录：负责 list_tools 聚合、路由与包装工具快照。
        self._tool_catalog = MCPToolCatalog(
            tool_caller=self._tool_executor.call_tool,
        )

        # 连接失败后的重试间隔（秒）。
        self._reconnect_seconds = reconnect_seconds

    async def connect(self, urls: str | list[str]) -> list[str]:
        """
        连接一个或多个 MCP URL，并返回对应服务名。

        连接策略：
        1. 输入 URL 先做清洗（strip + 去空）；
        2. 已连接 URL 幂等跳过；
        3. 未连接 URL 全部成功后才返回；
        4. 任一失败会在固定间隔后持续重试。
        """
        normalized_urls = self._normalize_urls(urls)
        if not normalized_urls:
            raise ValueError("MCP URL 列表为空，至少需要一个有效端点")

        unique_urls = list(dict.fromkeys(normalized_urls))
        pending_urls: list[str] = []
        for url in unique_urls:
            connected_server = self._connections.get_server_name_by_url(url)
            if connected_server is None:
                pending_urls.append(url)
                continue
            logger.info(
                "♻️ [MCPHub] URL 已连接，跳过重连，url='{}'，server='{}'",
                url,
                connected_server,
            )

        while pending_urls:
            failed_urls: list[str] = []
            for endpoint_url in pending_urls:
                try:
                    server_name = await self._connections.connect_once(
                        endpoint_url=endpoint_url,
                        wakeup_handler=self._wakeup_bus.handle_wakeup_notification,
                        name_resolver=self._resolve_unique_server_name,
                    )
                    logger.info(
                        "✅ [MCPHub] 服务连接成功，name='{}'，url='{}'",
                        server_name,
                        endpoint_url,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    failed_urls.append(endpoint_url)
                    logger.warning(
                        "⚠️ [MCPHub] 服务连接失败，将稍后重试，url='{}'，error='{}: {}'",
                        endpoint_url,
                        exc.__class__.__name__,
                        exc,
                    )

            if failed_urls:
                logger.warning(
                    "⚠️ [MCPHub] 仍有 {} 个 MCP 服务未连接，{:.1f}s 后重试",
                    len(failed_urls),
                    self._reconnect_seconds,
                )
                await asyncio.sleep(self._reconnect_seconds)
            pending_urls = failed_urls

        # 目标 URL 全部连接成功后，再统一刷新一次工具快照。
        await self._tool_catalog.refresh(self._connections.sessions)

        resolved_names: list[str] = []
        for url in normalized_urls:
            resolved_server = self._connections.get_server_name_by_url(url)
            if resolved_server is None:
                raise RuntimeError(f"连接完成后未找到 URL 对应服务名：{url}")
            resolved_names.append(resolved_server)

        logger.info(
            "🧠 [MCPHub] MCP 连接完成，目标URL数={}，连接服务数={}，工具数={}",
            len(unique_urls),
            self._connections.get_connected_server_count(),
            len(self._tool_catalog.get_tools()),
        )
        return resolved_names

    async def close(self) -> None:
        """关闭管理器并释放连接资源。"""
        # 清空工具快照，防止停止后误用旧工具。
        self._tool_catalog.clear()

        # 重置唤醒状态，避免残留旧 event/signal。
        self._wakeup_bus.reset()

        # 释放全部会话连接资源。
        await self._connections.stop()
        logger.info("🛑 [MCPHub] MCPManager 连接资源已释放")

    async def get_all_tools(self, refresh: bool = True) -> list[StructuredTool]:
        """获取所有包装后的工具列表。"""
        self._ensure_connected()
        if refresh:
            # 按需刷新工具目录，确保调用端拿到最新快照。
            await self._tool_catalog.refresh(self._connections.sessions)
        return self._tool_catalog.get_tools()

    def get_wakeup_event(self) -> asyncio.Event:
        """返回全局唤醒事件。"""
        self._ensure_connected()
        return self._wakeup_bus.get_event()

    async def wait_for_wakeup(self) -> None:
        """等待一条 MCP 唤醒通知。"""
        self._ensure_connected()
        await self._wakeup_bus.wait()

    def clear_wakeup_event(self) -> None:
        """清理唤醒事件标记。"""
        self._ensure_connected()
        self._wakeup_bus.clear()

    def get_last_wakeup_signal(self) -> WakeupSignal | None:
        """返回最近一次唤醒信号。"""
        self._ensure_connected()
        return self._wakeup_bus.get_last_signal()

    def get_last_wakeup_snapshot(self) -> dict[str, Any] | None:
        """返回最近一次唤醒信号快照（用于健康检查等观测）。"""
        self._ensure_connected()
        return self._wakeup_bus.get_last_snapshot()

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None,
    ) -> str:
        """
        调用指定 MCP 原始工具并返回解析后的字符串结果。

        参数：
        - server_name: MCP 服务别名；
        - tool_name: 服务内原始工具名；
        - arguments: 工具调用参数。
        """
        self._ensure_connected()
        # 具体调用逻辑下沉到执行器，管理器只做编排转发。
        return await self._tool_executor.call_tool(
            server_name=server_name,
            tool_name=tool_name,
            arguments=arguments,
        )

    async def call_wrapped_tool(
        self,
        wrapped_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """按包装后工具名调用 MCP 工具。"""
        self._ensure_connected()

        # 先做包装名 -> 原始路由解析。
        route = self._tool_catalog.resolve_route(wrapped_name)
        if route is None:
            raise ValueError(f"未知包装工具：{wrapped_name}")

        # 再复用统一 call_tool 执行链路。
        return await self.call_tool(
            server_name=route.server_name,
            tool_name=route.source_tool_name,
            arguments=arguments,
        )

    def get_connected_server_count(self) -> int:
        """返回当前已连接的 MCP 服务数量。"""
        return self._connections.get_connected_server_count()

    def _ensure_connected(self) -> None:
        """统一连接态断言，避免在无可用会话时访问运行资源。"""
        if self._connections.get_connected_server_count() <= 0:
            raise RuntimeError("MCPManager 尚未连接，请先调用 await connect(...)")

    def _resolve_unique_server_name(self, raw_server_name: str) -> str:
        """
        将服务原始名称规范化并保证唯一。

        命名规则：
        1. 非 [A-Za-z0-9_] 字符替换为 `_`；
        2. 去掉首尾 `_`；
        3. 为空时回退为 `mcp`；
        4. 数字开头时补前缀 `mcp_`；
        5. 冲突时自动追加 `_2`, `_3`...
        """
        base_name = self._normalize_server_name(raw_server_name)
        candidate = base_name
        suffix = 2
        while candidate in self._connections.sessions:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _normalize_server_name(raw_server_name: str) -> str:
        """将 MCP 返回服务名转换为合法且稳定的内部标识。"""
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", raw_server_name).strip("_").lower()
        if not normalized:
            normalized = "mcp"
        if normalized[0].isdigit():
            normalized = f"mcp_{normalized}"
        return normalized

    @staticmethod
    def _normalize_urls(urls: str | list[str]) -> list[str]:
        """把输入 URL 规范化为非空字符串列表。"""
        raw_items: list[str]
        if isinstance(urls, str):
            # 允许传入逗号分隔字符串，便于与环境变量直连。
            raw_items = urls.split(",")
        elif isinstance(urls, list):
            raw_items = []
            for item in urls:
                if not isinstance(item, str):
                    raise TypeError("MCP URL 列表仅允许字符串项")
                raw_items.append(item)
        else:
            raise TypeError("urls 必须是 str 或 list[str]")

        return [item.strip() for item in raw_items if item.strip()]
