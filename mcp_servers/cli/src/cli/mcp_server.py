from __future__ import annotations

import asyncio
import json
from typing import Any

import mcp.types as types
from loguru import logger
from mcp.server import Server
from mcp.server.session import ServerSession
from mcp.server.sse import SseServerTransport
from starlette.routing import Route

from cli.message_store import ChatStore

"""
MCP 服务定义与 SSE 接入端点。

职责边界：
1. 仅处理 MCP 协议相关逻辑（工具声明、工具调用、SSE 传输）；
2. 通过 `ChatStore` 协议与消息存储交互，不依赖具体存储实现。
"""

FETCH_MESSAGE_HISTORY_DEFAULT_PAGE = 1
FETCH_MESSAGE_HISTORY_DEFAULT_PAGE_SIZE = 50
FETCH_MESSAGE_HISTORY_MAX_PAGE_SIZE = 200


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

    用于维护活跃会话并向客户端推送 `new_message_alert` 通知。
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: set[ServerSession] = set()

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

    async def broadcast_new_message_alert(self, channel: str, message_id: int) -> None:
        """向全部活跃会话广播新消息唤醒通知。"""
        payload = json.dumps(
            {
                "event": "new_message_alert",
                "channel": channel,
                "message_id": message_id,
            },
            ensure_ascii=False,
        )

        async with self._lock:
            sessions_snapshot = list(self._sessions)

        failed_sessions: list[ServerSession] = []
        for session in sessions_snapshot:
            try:
                await session.send_progress_notification(
                    progress_token="new_message_alert",
                    progress=1.0,
                    message=payload,
                )
            except Exception as exc:
                failed_sessions.append(session)
                logger.warning(
                    "⚠️ [MCP] 广播唤醒通知失败，已标记会话待移除: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )

        if failed_sessions:
            async with self._lock:
                for session in failed_sessions:
                    self._sessions.discard(session)


def build_mcp_server(store: ChatStore, broadcaster: McpSessionBroadcaster) -> Server:
    """构建并注册 CLI MCP Server。"""
    mcp_server = Server("cli-mcp-server")

    @mcp_server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
        # 建立连接后客户端通常会先 list_tools，可借此登记活跃会话。
        await broadcaster.register_from_request_context(mcp_server)
        # 向 MCP 客户端声明当前可用工具及其 JSON Schema。
        return [
            types.Tool(
                name="send_cli_message",
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
                    "拉取当前所有渠道的未读消息，并在返回后清空未读池。"
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
        if name == "send_cli_message":
            if not arguments or "text" not in arguments:
                raise ValueError("调用 send_cli_message 缺少必须的参数 'text'")

            text = arguments["text"]
            if not isinstance(text, str):
                raise ValueError("send_cli_message 参数 'text' 必须是字符串")
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


class McpSseEndpoint:
    """
    MCP SSE 接入端点（原生 ASGI 形式）。

    关键点：
    - 不走 FastAPI 的 request->response 封装；
    - 由 `SseServerTransport` 全权负责响应发送，避免重复发送 `http.response.start`。
    """

    def __init__(self, mcp_server: Server, sse_transport: SseServerTransport) -> None:
        self._mcp_server = mcp_server
        self._sse_transport = sse_transport

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        logger.info("🔌 [MCP] 大脑已连接到 MCP SSE 隧道")
        async with self._sse_transport.connect_sse(scope, receive, send) as streams:
            await self._mcp_server.run(
                streams[0],
                streams[1],
                self._mcp_server.create_initialization_options(),
            )


class McpMessagesEndpoint:
    """MCP 消息上行端点（原生 ASGI 形式）。"""

    def __init__(self, sse_transport: SseServerTransport) -> None:
        self._sse_transport = sse_transport

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self._sse_transport.handle_post_message(scope, receive, send)


def build_mcp_server_routes(
    store: ChatStore,
    broadcaster: McpSessionBroadcaster,
) -> list[Route]:
    """构建 MCP 相关路由集合。"""
    mcp_server = build_mcp_server(store=store, broadcaster=broadcaster)
    # MCP SSE 传输层要求约定一个 POST 上行地址。
    sse_transport = SseServerTransport("/mcp/messages")
    return [
        Route("/mcp/sse", endpoint=McpSseEndpoint(mcp_server, sse_transport), methods=["GET"]),
        Route("/mcp/messages", endpoint=McpMessagesEndpoint(sse_transport), methods=["POST"]),
    ]
