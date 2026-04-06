from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from cli.mcp_server import (
    AICHAN_UNREAD_EVENTS_RESOURCE_URI,
    McpSessionBroadcaster,
    build_mcp_server_routes,
)
from cli.message_store import AsyncChatStore, ChatStore
from cli.models import ChatMessage, SendMessageRequest
from cli.settings import CLI_SERVER_CHANNEL_NAME, CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS

"""
FastAPI 应用装配层。

该模块负责：
1. 组装 HTTP 路由与 MCP 路由；
2. 将 `ChatStore` 作为依赖注入点；
3. 对外暴露 `build_cli_mcp_app` 供启动入口调用。
"""


def build_cli_mcp_app(store: ChatStore | None = None) -> FastAPI:
    """
    构建 CLI MCP FastAPI 应用。

    参数：
    - store: 可选消息存储实现，默认使用内存版 `AsyncChatStore`。
    """
    chat_store = (
        AsyncChatStore(default_channel=CLI_SERVER_CHANNEL_NAME)
        if store is None
        else store
    )
    broadcaster = McpSessionBroadcaster()
    mcp_routes, session_manager = build_mcp_server_routes(
        store=chat_store,
        broadcaster=broadcaster,
    )

    @asynccontextmanager
    async def app_lifespan(_: FastAPI):
        async with session_manager.run():
            await broadcaster.start()
            try:
                yield
            finally:
                await broadcaster.stop()

    app = FastAPI(title="CLI MCP Server", version="4.0.0", lifespan=app_lifespan)
    app.state.mcp_session_manager = session_manager

    # 挂载 MCP 协议路由：/mcp（Streamable HTTP）。
    app.router.routes.extend(mcp_routes)

    @app.get("/health")
    async def health() -> dict[str, object]:
        """健康检查端点。"""
        return {"ok": True, "service": "cli-mcp-server"}

    @app.get("/v1/messages", response_model=list[ChatMessage])
    async def list_messages(
        after_id: int = Query(default=0, ge=0)
    ) -> list[ChatMessage]:
        """按游标增量拉取消息。"""
        return await chat_store.list_messages(after_id=after_id)

    @app.get("/v1/events")
    async def stream_events(
        request: Request, after_id: int = Query(default=0, ge=0)
    ) -> StreamingResponse:
        """SSE 消息流端点，持续推送新增消息。"""

        async def _event_generator():
            last_id = after_id
            try:
                while True:
                    # 客户端断开后立即退出，避免无意义循环。
                    if await request.is_disconnected():
                        break
                    messages = await chat_store.wait_for_messages(
                        last_id, CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS
                    )
                    if not messages:
                        # 定期发送心跳，防止中间代理或客户端误判连接失活。
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
                # SSE 常见响应头：禁用缓存与反向代理缓冲。
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/messages", response_model=ChatMessage, status_code=201)
    async def send_message(payload: SendMessageRequest) -> ChatMessage:
        """写入一条消息。该端点主要供人类端 UI 调用。"""
        try:
            message = await chat_store.send_message(
                sender=payload.sender, text=payload.text
            )
            logger.info("👤 [UI] 收到人类消息: {}", message.text)
            if message.sender == "user":
                broadcaster.enqueue_resource_updated(
                    resource_uri=AICHAN_UNREAD_EVENTS_RESOURCE_URI,
                )
            return message
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
