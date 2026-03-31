from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from cli_server import (
    CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS,
    CLIMessageService,
    ChatMessage,
    SendMessageRequest,
)


def register_cli_api_routes(app: FastAPI, service: CLIMessageService) -> None:
    """向 FastAPI 应用注册 CLI 网关 API 路由。"""

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "service": "cli_gateway"}

    @app.get("/v1/messages", response_model=list[ChatMessage])
    async def list_messages(
        after_id: int = Query(default=0, ge=0)
    ) -> list[ChatMessage]:
        return await service.list_messages(after_id=after_id)

    @app.get("/v1/events")
    async def stream_events(
        request: Request,
        after_id: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        """SSE 接口：推送增量消息，支持断点续传与 Keep-Alive 保活。"""

        async def _event_generator():
            last_id = after_id
            logger.info("📡 [CLIGateway] SSE 客户端已连接，起始 ID={}", after_id)
            try:
                while True:
                    if await request.is_disconnected():
                        logger.info("📡 [CLIGateway] SSE 客户端主动断开连接")
                        break

                    messages = await service.wait_incremental_messages(
                        after_id=last_id,
                        timeout_seconds=CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS,
                    )

                    if not messages:
                        yield ": keep-alive\n\n"
                        continue

                    for message in messages:
                        if await request.is_disconnected():
                            return

                        payload = message.model_dump_json(by_alias=True)
                        logger.info(
                            "📡 [CLIGateway] 推送 SSE 消息，message_id={}", message.id
                        )

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
            message = await service.save_message(payload)
            logger.info(
                "✅ [CLIGateway] 收到消息写入，message_id={}，sender='{}'",
                message.id,
                message.sender,
            )
            return message
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
