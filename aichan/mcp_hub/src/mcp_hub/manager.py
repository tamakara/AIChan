from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Coroutine

import mcp.types as mcp_types
from langchain_core.tools import StructuredTool
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client

from core.logger import logger
from .models import MCPServerConfig
from .tools_wrapper import build_mcp_structured_tool, parse_call_tool_result


@dataclass(frozen=True, slots=True)
class _WrappedToolRoute:
    """包装后工具名到 MCP 原始工具的路由映射。"""

    wrapped_name: str
    server_name: str
    source_tool_name: str


class MCPManager:
    """
    MCP 多服务连接管理器。

    设计目标：
    1. 统一维护 MCP 会话生命周期；
    2. 动态发现并包装工具；
    3. 为同步与异步调用链都提供稳定接口。
    """

    def __init__(
        self,
        server_configs: list[MCPServerConfig] | None = None,
    ) -> None:
        self._server_configs = server_configs or [
            MCPServerConfig(
                name="cli_mcp",
                sse_url="http://localhost:9000/mcp/sse",
                required=True,
            )
        ]

        self._server_required: dict[str, bool] = {
            config.name: config.required for config in self._server_configs
        }
        self._sessions: dict[str, ClientSession] = {}
        self._routes: dict[str, _WrappedToolRoute] = {}
        self._wrapped_tools: list[StructuredTool] = []

        self._exit_stack: AsyncExitStack | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._started = False
        self._refresh_lock = asyncio.Lock()

    async def start(self) -> None:
        """启动管理器并建立 MCP 会话。"""
        if self._started:
            logger.warning("♻️ [MCPHub] MCPManager 已启动，忽略重复调用")
            return

        self._event_loop = asyncio.get_running_loop()
        self._exit_stack = AsyncExitStack()
        connected_count = 0

        logger.info("🚀 [MCPHub] 启动连接管理，目标服务数={}", len(self._server_configs))

        try:
            for config in self._server_configs:
                try:
                    session = await self._connect_single_server(config=config)
                    self._sessions[config.name] = session
                    connected_count += 1
                    logger.info(
                        "✅ [MCPHub] 服务连接成功，name='{}'，url='{}'",
                        config.name,
                        config.sse_url,
                    )
                except Exception as exc:
                    if config.required:
                        raise RuntimeError(
                            f"强依赖 MCP 服务连接失败：name='{config.name}', url='{config.sse_url}'"
                        ) from exc
                    logger.warning(
                        "⚠️ [MCPHub] 可选服务连接失败，已忽略，name='{}'，url='{}'，error='{}: {}'",
                        config.name,
                        config.sse_url,
                        exc.__class__.__name__,
                        exc,
                    )

            if connected_count == 0:
                raise RuntimeError("未连接到任何 MCP 服务，无法启动 MCPManager")

            await self._refresh_tools()
            self._started = True
            logger.info(
                "🧠 [MCPHub] MCPManager 启动完成，连接服务数={}，工具数={}",
                connected_count,
                len(self._wrapped_tools),
            )
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        """关闭管理器并释放连接资源。"""
        exit_stack = self._exit_stack
        self._started = False
        self._sessions = {}
        self._routes = {}
        self._wrapped_tools = []
        self._event_loop = None
        self._exit_stack = None

        if exit_stack is not None:
            await exit_stack.aclose()
            logger.info("🛑 [MCPHub] MCPManager 连接资源已释放")

    async def get_all_tools(self, refresh: bool = True) -> list[StructuredTool]:
        """获取所有包装后的工具列表。"""
        self._ensure_started()
        if refresh:
            await self._refresh_tools()
        return list(self._wrapped_tools)

    def get_all_tools_sync(
        self,
        refresh: bool = False,
        timeout_seconds: float = 15.0,
    ) -> list[StructuredTool]:
        """
        同步获取工具列表。

        该接口供当前线程化 SignalHub 链路使用。
        """
        return self._run_coroutine_sync(
            self.get_all_tools(refresh=refresh),
            timeout_seconds=timeout_seconds,
        )

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
        self._ensure_started()
        session = self._sessions.get(server_name)
        if session is None:
            raise ValueError(f"未知 MCP 服务：{server_name}")

        logger.info(
            "⚙️ [MCPHub] 调用 MCP 工具，server='{}'，tool='{}'",
            server_name,
            tool_name,
        )
        result = await session.call_tool(
            tool_name,
            arguments=arguments or None,
        )
        parsed = parse_call_tool_result(result)
        logger.info(
            "✅ [MCPHub] MCP 工具调用完成，server='{}'，tool='{}'，返回长度={}字符",
            server_name,
            tool_name,
            len(parsed),
        )
        return parsed

    def call_tool_sync(
        self,
        *,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> str:
        """同步调用 MCP 工具（线程桥接）。"""
        return self._run_coroutine_sync(
            self.call_tool(
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
            ),
            timeout_seconds=timeout_seconds,
        )

    async def call_wrapped_tool(
        self,
        wrapped_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """按包装后工具名调用 MCP 工具。"""
        self._ensure_started()
        route = self._routes.get(wrapped_name)
        if route is None:
            raise ValueError(f"未知包装工具：{wrapped_name}")
        return await self.call_tool(
            server_name=route.server_name,
            tool_name=route.source_tool_name,
            arguments=arguments,
        )

    def get_connected_server_count(self) -> int:
        """返回当前已连接的 MCP 服务数量。"""
        return len(self._sessions)

    async def _connect_single_server(self, config: MCPServerConfig) -> ClientSession:
        if self._exit_stack is None:
            raise RuntimeError("MCPManager 尚未初始化 ExitStack")

        streams = await self._exit_stack.enter_async_context(
            sse_client(config.sse_url)
        )
        session = await self._exit_stack.enter_async_context(
            ClientSession(streams[0], streams[1])
        )
        await session.initialize()
        return session

    async def _refresh_tools(self) -> None:
        """刷新工具缓存快照。"""
        self._ensure_started_or_starting()
        async with self._refresh_lock:
            wrapped_tools: list[StructuredTool] = []
            routes: dict[str, _WrappedToolRoute] = {}

            for server_name, session in self._sessions.items():
                try:
                    listed_tools = await session.list_tools()
                except Exception as exc:
                    is_required = self._server_required.get(server_name, True)
                    if is_required:
                        raise RuntimeError(
                            f"强依赖服务工具发现失败：server='{server_name}'"
                        ) from exc
                    logger.warning(
                        "⚠️ [MCPHub] 可选服务工具发现失败，已跳过，server='{}'，error='{}: {}'",
                        server_name,
                        exc.__class__.__name__,
                        exc,
                    )
                    continue

                for source_tool in listed_tools.tools:
                    wrapped_name = self._build_wrapped_tool_name(
                        server_name=server_name,
                        source_tool=source_tool,
                    )
                    route = _WrappedToolRoute(
                        wrapped_name=wrapped_name,
                        server_name=server_name,
                        source_tool_name=source_tool.name,
                    )
                    routes[wrapped_name] = route

                    wrapped_tools.append(
                        self._build_structured_tool(
                            route=route,
                            source_tool=source_tool,
                        )
                    )

            self._routes = routes
            self._wrapped_tools = wrapped_tools
            logger.info("🔍 [MCPHub] 工具快照刷新完成，工具总数={}", len(self._wrapped_tools))

    def _build_structured_tool(
        self,
        *,
        route: _WrappedToolRoute,
        source_tool: mcp_types.Tool,
    ) -> StructuredTool:
        def _sync_executor(arguments: dict[str, Any]) -> str:
            return self.call_tool_sync(
                server_name=route.server_name,
                tool_name=route.source_tool_name,
                arguments=arguments,
            )

        async def _async_executor(arguments: dict[str, Any]) -> str:
            return await self.call_tool(
                server_name=route.server_name,
                tool_name=route.source_tool_name,
                arguments=arguments,
            )

        return build_mcp_structured_tool(
            wrapped_name=route.wrapped_name,
            server_name=route.server_name,
            source_tool=source_tool,
            sync_executor=_sync_executor,
            async_executor=_async_executor,
        )

    @staticmethod
    def _build_wrapped_tool_name(
        *,
        server_name: str,
        source_tool: mcp_types.Tool,
    ) -> str:
        # 同名工具冲突策略：固定 server_alias__tool_name。
        return f"{server_name}__{source_tool.name}"

    def _run_coroutine_sync(
        self,
        coroutine: Coroutine[Any, Any, Any],
        *,
        timeout_seconds: float,
    ) -> Any:
        self._ensure_started()
        event_loop = self._event_loop
        if event_loop is None:
            raise RuntimeError("MCPManager 事件循环未就绪，无法同步桥接调用")

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is event_loop:
            raise RuntimeError("不能在 MCPManager 所在事件循环中调用同步接口，请改用异步接口")

        future = asyncio.run_coroutine_threadsafe(coroutine, event_loop)
        return future.result(timeout=timeout_seconds)

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("MCPManager 尚未启动，请先调用 await start()")

    def _ensure_started_or_starting(self) -> None:
        if self._exit_stack is None:
            raise RuntimeError("MCPManager 尚未启动，请先调用 await start()")
