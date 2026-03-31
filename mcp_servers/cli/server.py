from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from starlette.routing import Route

# 🚀 引入 MCP 官方最稳健的底层 SDK
import mcp.types as types
from mcp.server import Server
from mcp.server.sse import SseServerTransport

# ==========================================
# ⚙️ 全局配置
# ==========================================
CLI_SERVER_HOST = os.getenv("CLI_SERVER_HOST", "localhost")
CLI_SERVER_PORT = int(os.getenv("CLI_SERVER_PORT", "9000"))
CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS = 1
CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS = 2
CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS = 1.0

CLIChannelIdentity = Literal["ai", "user"]


# ==========================================
# 📦 数据模型
# ==========================================
class SendMessageRequest(BaseModel):
    sender: CLIChannelIdentity
    text: str = Field(..., min_length=1)


class ChatMessage(BaseModel):
    id: int = Field(..., ge=1)
    sender: CLIChannelIdentity
    text: str
    created_at: str


# ==========================================
# 🧠 异步存储 (原生 AsyncIO)
# ==========================================
class AsyncChatStore:
    def __init__(self) -> None:
        self._messages: list[ChatMessage] = []
        self._next_id = 1
        self._lock = asyncio.Lock()
        self._new_message_cond = asyncio.Condition(self._lock)

    async def list_messages(self, after_id: int = 0) -> list[ChatMessage]:
        async with self._lock:
            return [msg for msg in self._messages if msg.id > after_id]

    async def wait_for_messages(
        self, after_id: int, timeout_seconds: float
    ) -> list[ChatMessage]:
        async with self._new_message_cond:
            messages = [msg for msg in self._messages if msg.id > after_id]
            if not messages:
                try:
                    await asyncio.wait_for(
                        self._new_message_cond.wait(), timeout=timeout_seconds
                    )
                except asyncio.TimeoutError:
                    pass
                messages = [msg for msg in self._messages if msg.id > after_id]
            return messages

    async def send_message(self, sender: CLIChannelIdentity, text: str) -> ChatMessage:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text 不能为空")
        async with self._lock:
            message = ChatMessage(
                id=self._next_id,
                sender=sender,
                text=clean_text,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._messages.append(message)
            self._next_id += 1
            self._new_message_cond.notify_all()
        return message


# 1. 全局单例存储
store = AsyncChatStore()


# ==========================================
# 🛠️ MCP Server 核心定义 (底层硬核写法)
# ==========================================
mcp_server = Server("cli-mcp-server")


# 明确声明工具的 Schema，大模型会严格按照这个格式调用
@mcp_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="send_cli_message",
            description="向 CLI 终端用户发送一条文本消息。当你想回复用户的提问，或者主动发起对话时，请调用此工具。",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要发送给用户的文本内容"}
                },
                "required": ["text"],
            },
        )
    ]


# 真正执行工具的业务逻辑
@mcp_server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name == "send_cli_message":
        if not arguments or "text" not in arguments:
            raise ValueError("调用 send_cli_message 缺少必须的参数 'text'")

        text = arguments["text"]
        logger.info("🤖 [MCP Tool] 收到大模型调用，准备发送消息: {}", text)
        await store.send_message(sender="ai", text=text)

        return [
            types.TextContent(type="text", text=f"✅ 已成功将消息发送给用户: '{text}'")
        ]
    raise ValueError(f"未知的 Tool: {name}")


# ==========================================
# 🌐 FastAPI 与 MCP 传输层融合
# ==========================================
# 告诉底层 SSE 传输层，客户端发指令时应该 POST 到哪个路由
sse_transport = SseServerTransport("/mcp/messages")


class _McpSseEndpoint:
    """
    MCP SSE 接入端点（原生 ASGI 形式）。

    关键点：
    - 不走 FastAPI 的 request->response 封装；
    - 由 `SseServerTransport` 全权负责响应发送，避免重复发送 `http.response.start`。
    """

    async def __call__(self, scope, receive, send) -> None:
        logger.info("🔌 [MCP] 大脑已连接到 MCP SSE 隧道")
        async with sse_transport.connect_sse(scope, receive, send) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )


class _McpMessagesEndpoint:
    """MCP 消息上行端点（原生 ASGI 形式）。"""

    async def __call__(self, scope, receive, send) -> None:
        await sse_transport.handle_post_message(scope, receive, send)


def build_cli_mcp_app() -> FastAPI:
    app = FastAPI(title="CLI MCP Server", version="4.0.0")

    # ----------------------------------------
    # 👽 AICHAN 大脑的接入隧道 (MCP 官方底层接口)
    # ----------------------------------------
    app.router.routes.append(
        Route("/mcp/sse", endpoint=_McpSseEndpoint(), methods=["GET"])
    )
    app.router.routes.append(
        Route("/mcp/messages", endpoint=_McpMessagesEndpoint(), methods=["POST"])
    )

    # ----------------------------------------
    # 👤 人类终端 UI 的传统接口 (/v1/*)
    # ----------------------------------------
    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "service": "cli_mcp_server"}

    @app.get("/v1/messages", response_model=list[ChatMessage])
    async def list_messages(
        after_id: int = Query(default=0, ge=0)
    ) -> list[ChatMessage]:
        return await store.list_messages(after_id=after_id)

    @app.get("/v1/events")
    async def stream_events(
        request: Request, after_id: int = Query(default=0, ge=0)
    ) -> StreamingResponse:
        async def _event_generator():
            last_id = after_id
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    messages = await store.wait_for_messages(
                        last_id, CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS
                    )
                    if not messages:
                        yield ": keep-alive\n\n"
                        continue
                    for message in messages:
                        if await request.is_disconnected():
                            return
                        payload = message.model_dump_json(by_alias=True)
                        yield f"id: {message.id}\nevent: message\ndata: {payload}\n\n"
                        last_id = message.id
            except asyncio.CancelledError:
                pass

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/messages", response_model=ChatMessage, status_code=201)
    async def send_message(payload: SendMessageRequest) -> ChatMessage:
        try:
            message = await store.send_message(sender=payload.sender, text=payload.text)
            logger.info("👤 [UI] 收到人类消息: {}", message.text)
            return message
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def main() -> None:
    logger.info("🚀 [CLIServer] 准备启动，混合原生 MCP + FastAPI...")
    uvicorn.run(
        build_cli_mcp_app(),
        host=CLI_SERVER_HOST,
        port=CLI_SERVER_PORT,
        log_level="info",
        access_log=False,
        timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
        timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    )


if __name__ == "__main__":
    main()
