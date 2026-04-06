"""
MCP 多服务连接池实现。

该模块聚焦在“连接生命周期管理”：
1. 按 URL 建立 MCP 会话；
2. 统一注册唤醒通知处理器；
3. 在失败或停止时完成资源回收，避免连接泄露。
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack

import mcp.types as mcp_types
from core.logger import logger
from mcp.client.streamable_http import streamable_http_client

from mcp_hub.session import MCPClientSession, WakeupHandler, bind_wakeup_notification_handler


class MCPConnectionPool:
    """
    管理 MCP 多服务连接生命周期。

    职责边界：
    1. 按 URL 建立会话连接；
    2. 在连接成功后注册唤醒通知处理器；
    3. 统一管理连接资源释放；
    4. 提供 URL -> server_name 映射查询能力。
    """

    def __init__(self) -> None:
        # 已建立连接的会话映射：server_name -> session。
        self._sessions: dict[str, MCPClientSession] = {}

        # URL 到 server_name 的稳定映射（用于幂等 connect 与结果回填）。
        self._url_to_server_name: dict[str, str] = {}

        # 统一管理所有异步上下文，close 时一次性释放。
        self._exit_stack: AsyncExitStack | None = None

    @property
    def sessions(self) -> dict[str, MCPClientSession]:
        """返回当前会话映射（由上层只读使用）。"""
        return self._sessions

    def get_connected_server_count(self) -> int:
        """返回已连接服务数量，供 health 与启动日志使用。"""
        return len(self._sessions)

    def get_server_name_by_url(self, endpoint_url: str) -> str | None:
        """根据 URL 查询已连接的服务名。"""
        return self._url_to_server_name.get(endpoint_url.strip())

    async def connect_once(
        self,
        *,
        endpoint_url: str,
        wakeup_handler: WakeupHandler,
        name_resolver: Callable[[str], str],
    ) -> str:
        """
        连接单个 MCP URL 并返回最终服务名。

        行为说明：
        1. 若 URL 已连接，直接返回已存在服务名（幂等）；
        2. 服务名在 initialize 后从 serverInfo.name 解析并规范化；
        3. 仅在全部初始化成功后才会将资源挂载到全局资源栈。
        """
        clean_url = endpoint_url.strip()
        if not clean_url:
            raise ValueError("endpoint_url 不能为空")

        existing_server = self._url_to_server_name.get(clean_url)
        if existing_server is not None:
            return existing_server

        if self._exit_stack is None:
            self._exit_stack = AsyncExitStack()

        # 先在临时栈里完成初始化，成功后再挂到全局 ExitStack，
        # 避免初始化失败时触发跨任务的 cancel scope 退出异常。
        temp_stack = AsyncExitStack()
        try:
            read_stream, write_stream, _ = await temp_stack.enter_async_context(
                streamable_http_client(clean_url)
            )
            session = await temp_stack.enter_async_context(
                MCPClientSession(
                    read_stream,
                    write_stream,
                )
            )

            # 必须在 initialize 后才能拿到 serverInfo 并绑定唤醒处理器。
            initialize_result: mcp_types.InitializeResult = await session.initialize()
            resolved_server_name = name_resolver(str(initialize_result.serverInfo.name))

            if resolved_server_name in self._sessions:
                raise RuntimeError(
                    f"服务名冲突：server='{resolved_server_name}', url='{clean_url}'"
                )

            bind_wakeup_notification_handler(
                session=session,
                server_name=resolved_server_name,
                handler=wakeup_handler,
            )
        except BaseException as exc:
            try:
                # 初始化失败时立即清理临时资源，避免连接泄露。
                await temp_stack.aclose()
            except BaseException as close_exc:
                # 清理阶段异常仅记日志，不覆盖主异常信息。
                logger.debug(
                    "♻️ [MCPHub] 忽略连接失败后的清理异常，url='{}'，error='{}: {}'",
                    clean_url,
                    close_exc.__class__.__name__,
                    close_exc,
                )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                # 进程级终止信号必须原样抛出。
                raise
            raise RuntimeError(f"MCP 会话初始化失败：url='{clean_url}'") from exc

        # 仅在全部初始化成功后，把临时资源栈转移到全局资源栈。
        persisted_stack = temp_stack.pop_all()
        self._exit_stack.push_async_callback(persisted_stack.aclose)
        self._sessions[resolved_server_name] = session
        self._url_to_server_name[clean_url] = resolved_server_name
        return resolved_server_name

    async def close(self) -> None:
        """释放全部连接资源并清空会话状态。"""
        exit_stack = self._exit_stack

        # 先切断外部可见状态，避免 stop 过程中被再次读取。
        self._sessions = {}
        self._url_to_server_name = {}
        self._exit_stack = None

        if exit_stack is not None:
            try:
                # 统一关闭所有连接上下文。
                await exit_stack.aclose()
            except Exception as exc:
                # 关闭阶段异常只做调试日志，不阻断停止流程。
                logger.debug(
                    "♻️ [MCPHub] 忽略停止阶段连接清理异常: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
