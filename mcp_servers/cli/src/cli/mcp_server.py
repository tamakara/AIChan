from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.types as types
from loguru import logger
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.session import ServerSession
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Route

from cli.message_store import ChatStore

"""
MCP 服务定义与 Streamable HTTP 接入端点。

职责边界：
1. 仅处理 MCP 协议相关逻辑（工具声明、工具调用、Streamable HTTP 传输）；
2. 通过 `ChatStore` 协议与消息存储交互，不依赖具体存储实现。
"""

FETCH_MESSAGE_HISTORY_DEFAULT_PAGE = 1
FETCH_MESSAGE_HISTORY_DEFAULT_PAGE_SIZE = 50
FETCH_MESSAGE_HISTORY_MAX_PAGE_SIZE = 200
AICHAN_RESOURCE_UPDATED_METHOD = "notifications/resources/updated"
AICHAN_UNREAD_EVENTS_RESOURCE_URI = "aichan://events/unread"
SEND_TOOL_NAME = "send_message"


def _read_int_argument(
    arguments: dict[str, Any],
    name: str,
    *,
    minimum: int,
    default: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """读取并校验整数参数。"""
    if name not in arguments:
        return default

    value = arguments[name]
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须是整数")
    if value < minimum:
        raise ValueError(f"{name} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} 不能大于 {maximum}")
    return value


class McpSessionBroadcaster:
    """
    MCP 会话广播器。

    用于维护活跃会话并异步推送 `resources/updated` 原生通知。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: set[ServerSession] = set()
        self._resource_signal_queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动后台通知分发任务。"""
        if self._worker_task is not None and not self._worker_task.done():
            logger.warning("♻️ [MCP] 会话广播器已启动，忽略重复调用")
            return
        self._worker_task = asyncio.create_task(
            self._resource_signal_worker_loop(),
            name="cli-mcp-resource-signal-broadcaster",
        )

    async def stop(self) -> None:
        """停止后台通知分发任务。"""
        task = self._worker_task
        self._worker_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🛑 [MCP] 会话广播器已停止")

    async def register(self, session: ServerSession) -> None:
        """注册活跃会话（幂等）。"""
        async with self._lock:
            self._sessions.add(session)

    async def unregister(self, session: ServerSession) -> None:
        """移除会话（幂等）。"""
        async with self._lock:
            self._sessions.discard(session)

    async def register_from_request_context(self, mcp_server: Server) -> None:
        """
        从 MCP request context 中提取当前会话并注册。

        说明：只有在 MCP 请求处理上下文中才可读取 request_context。
        """
        try:
            context = mcp_server.request_context
        except LookupError:
            # 若当前不在请求上下文，直接忽略，不抛错。
            return
        await self.register(context.session)

    def enqueue_resource_updated(self, *, resource_uri: str) -> None:
        """非阻塞入队一条资源更新信号。"""
        clean_uri = resource_uri.strip()
        if not clean_uri:
            logger.warning(
                "⚠️ [MCP] 忽略无效资源更新信号，uri='{}'",
                resource_uri,
            )
            return
        self._resource_signal_queue.put_nowait(clean_uri)

    async def _resource_signal_worker_loop(self) -> None:
        """后台消费资源信号队列并广播 MCP 原生资源更新通知。"""
        while True:
            resource_uri = await self._resource_signal_queue.get()
            try:
                await self._broadcast_resource_updated(resource_uri=resource_uri)
            except Exception as exc:
                logger.error(
                    "❌ [MCP] 广播资源更新通知失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
            finally:
                self._resource_signal_queue.task_done()

    async def _broadcast_resource_updated(self, *, resource_uri: str) -> None:
        """向全部活跃会话广播 `notifications/resources/updated`。"""
        async with self._lock:
            sessions_snapshot = list(self._sessions)

        failed_sessions: list[ServerSession] = []
        for session in sessions_snapshot:
            try:
                await session.send_resource_updated(uri=resource_uri)
            except Exception as exc:
                failed_sessions.append(session)
                logger.warning(
                    "⚠️ [MCP] 广播资源更新通知失败，已标记会话待移除: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
            else:
                logger.info(
                    "🔔 [MCP] 已发送资源更新通知，method='{}'，uri='{}'",
                    AICHAN_RESOURCE_UPDATED_METHOD,
                    resource_uri,
                )

        if failed_sessions:
            async with self._lock:
                for session in failed_sessions:
                    self._sessions.discard(session)


def build_mcp_server(store: ChatStore, broadcaster: McpSessionBroadcaster) -> Server:
    """构建并注册 CLI MCP Server。"""
    mcp_server = Server("cli-mcp-server")

    @mcp_server.list_resources()
    async def handle_list_resources() -> list[types.Resource]:
        # 仅暴露“有未读事件信号”资源，不承载业务消息内容。
        await broadcaster.register_from_request_context(mcp_server)
        return [
            types.Resource(
                name="unread_events",
                uri=AICHAN_UNREAD_EVENTS_RESOURCE_URI,
                description=(
                    "Signal-only resource. Use fetch_unread_messages tool to pull "
                    "business payload."
                ),
                mimeType="application/json",
            )
        ]

    @mcp_server.read_resource()
    async def handle_read_resource(uri: types.AnyUrl) -> list[ReadResourceContents]:
        await broadcaster.register_from_request_context(mcp_server)
        if str(uri) != AICHAN_UNREAD_EVENTS_RESOURCE_URI:
            raise ValueError(f"未知资源 URI: {uri}")
        signal_payload = json.dumps(
            {
                "resource": AICHAN_UNREAD_EVENTS_RESOURCE_URI,
                "mode": "signal_only",
                "data_source": "fetch_unread_messages",
            },
            ensure_ascii=False,
        )
        return [
            ReadResourceContents(
                content=signal_payload,
                mime_type="application/json",
            )
        ]

    @mcp_server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        # 建立连接后客户端通常会先 list_tools，可借此登记活跃会话。
        await broadcaster.register_from_request_context(mcp_server)
        # 向 MCP 客户端声明当前可用工具及其 JSON Schema。
        return [
            types.Tool(
                name=SEND_TOOL_NAME,
                description="向 CLI 终端用户发送一条文本消息。当你想回复用户的提问，或者主动发起对话时，请调用此工具。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "要发送给用户的文本内容",
                        }
                    },
                    "required": ["text"],
                },
            ),
            types.Tool(
                name="fetch_unread_messages",
                description=(
                    "拉取当前所有渠道的未读事件，并在返回后原子清空事件队列。"
                    "返回结果是 JSON 列表，每项包含 channel/message_id/sender/text/created_at。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            types.Tool(
                name="fetch_message_history",
                description=(
                    "主动查询历史消息（包含已读与未读，含 user/ai）。"
                    "支持 page/page_size 分页参数，结果按时间倒序（新到旧）返回。"
                    "返回结果是 JSON 列表，每项包含 id/sender/text/created_at。"
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "page": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "default": FETCH_MESSAGE_HISTORY_DEFAULT_PAGE,
                            "description": "页码（从 1 开始），默认 1",
                        },
                        "page_size": {
                            "type": ["integer", "null"],
                            "minimum": 1,
                            "maximum": FETCH_MESSAGE_HISTORY_MAX_PAGE_SIZE,
                            "default": FETCH_MESSAGE_HISTORY_DEFAULT_PAGE_SIZE,
                            "description": "每页条数，默认 50",
                        },
                    },
                    "additionalProperties": False,
                },
            ),
        ]

    @mcp_server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> types.CallToolResult | list[
        types.TextContent | types.ImageContent | types.EmbeddedResource
    ]:
        await broadcaster.register_from_request_context(mcp_server)
        # 统一工具调用入口：根据工具名路由到具体业务处理。
        if name == SEND_TOOL_NAME:
            if not arguments or "text" not in arguments:
                raise ValueError(f"调用 {SEND_TOOL_NAME} 缺少必须的参数 'text'")

            text = arguments["text"]
            if not isinstance(text, str):
                raise ValueError(f"{SEND_TOOL_NAME} 参数 'text' 必须是字符串")
            logger.info("🤖 [MCP Tool] 收到大模型调用，准备发送消息: {}", text)
            # MCP 工具调用最终落到消息存储，供 UI 端读取或 SSE 推送。
            await store.send_message(sender="ai", text=text)

            return [
                types.TextContent(type="text", text=f"✅ 已成功将消息发送给用户: '{text}'")
            ]
        if name == "fetch_unread_messages":
            if arguments:
                raise ValueError("fetch_unread_messages 不接受任何参数")

            unread_messages = await store.fetch_unread_messages()
            unread_payload = [message.model_dump(mode="json") for message in unread_messages]
            unread_json = json.dumps(unread_payload, ensure_ascii=False)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=unread_json,
                    )
                ],
                isError=False,
            )
        if name == "fetch_message_history":
            history_args = arguments or {}
            if not isinstance(history_args, dict):
                raise ValueError("fetch_message_history 参数必须是 JSON 对象")

            allowed_keys = {"page", "page_size"}
            unknown_keys = sorted(str(key) for key in history_args.keys() if key not in allowed_keys)
            if unknown_keys:
                raise ValueError(
                    "fetch_message_history 存在未知参数: " + ", ".join(unknown_keys)
                )

            page = _read_int_argument(
                history_args,
                "page",
                minimum=1,
                default=FETCH_MESSAGE_HISTORY_DEFAULT_PAGE,
            )
            page_size = _read_int_argument(
                history_args,
                "page_size",
                minimum=1,
                maximum=FETCH_MESSAGE_HISTORY_MAX_PAGE_SIZE,
                default=FETCH_MESSAGE_HISTORY_DEFAULT_PAGE_SIZE,
            )

            if page is None:
                page = FETCH_MESSAGE_HISTORY_DEFAULT_PAGE
            if page_size is None:
                page_size = FETCH_MESSAGE_HISTORY_DEFAULT_PAGE_SIZE

            history_messages = await store.list_message_history(
                page=page,
                page_size=page_size,
            )
            history_payload = [message.model_dump(mode="json") for message in history_messages]
            history_json = json.dumps(history_payload, ensure_ascii=False)
            return types.CallToolResult(
                content=[
                    types.TextContent(
                        type="text",
                        text=history_json,
                    )
                ],
                isError=False,
            )
        raise ValueError(f"未知的 Tool: {name}")

    return mcp_server


class McpStreamableHttpEndpoint:
    """
    MCP Streamable HTTP 接入端点（原生 ASGI 形式）。
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def build_mcp_server_routes(
    store: ChatStore,
    broadcaster: McpSessionBroadcaster,
) -> tuple[list[Route], StreamableHTTPSessionManager]:
    """构建 MCP Streamable HTTP 路由与会话管理器。"""
    mcp_server = build_mcp_server(store=store, broadcaster=broadcaster)
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        stateless=False,
    )
    return [
        Route(
            "/mcp",
            endpoint=McpStreamableHttpEndpoint(session_manager),
            methods=["GET", "POST", "DELETE"],
        )
    ], session_manager
