from __future__ import annotations

from typing import Any

import mcp.types as types
from loguru import logger
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.routing import Route

from .message_store import ChatStore

"""
MCP 服务定义与 SSE 接入端点。

职责边界：
1. 仅处理 MCP 协议相关逻辑（工具声明、工具调用、SSE 传输）；
2. 通过 `ChatStore` 协议与消息存储交互，不依赖具体存储实现。
"""


def build_mcp_server(store: ChatStore) -> Server:
    """构建并注册 CLI MCP Server。"""
    mcp_server = Server("cli-mcp-server")

    @mcp_server.list_tools()
    async def handle_list_tools() -> list[types.Tool]:
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
            )
        ]

    @mcp_server.call_tool()
    async def handle_call_tool(
        name: str, arguments: dict | None
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        # 统一工具调用入口：根据工具名路由到具体业务处理。
        if name == "send_cli_message":
            if not arguments or "text" not in arguments:
                raise ValueError("调用 send_cli_message 缺少必须的参数 'text'")

            text = arguments["text"]
            logger.info("🤖 [MCP Tool] 收到大模型调用，准备发送消息: {}", text)
            # MCP 工具调用最终落到消息存储，供 UI 端读取或 SSE 推送。
            await store.send_message(sender="ai", text=text)

            return [
                types.TextContent(type="text", text=f"✅ 已成功将消息发送给用户: '{text}'")
            ]
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


def build_mcp_server_routes(store: ChatStore) -> list[Route]:
    """构建 MCP 相关路由集合。"""
    mcp_server = build_mcp_server(store=store)
    # MCP SSE 传输层要求约定一个 POST 上行地址。
    sse_transport = SseServerTransport("/mcp/messages")
    return [
        Route("/mcp/sse", endpoint=McpSseEndpoint(mcp_server, sse_transport), methods=["GET"]),
        Route("/mcp/messages", endpoint=McpMessagesEndpoint(sse_transport), methods=["POST"]),
    ]
