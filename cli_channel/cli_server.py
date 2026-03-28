from __future__ import annotations

import asyncio
import json
import os
import threading
from datetime import datetime, timezone
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# cli_server 默认通信地址，可通过环境变量覆盖。
CLI_SERVER_HOST = os.getenv("CLI_SERVER_HOST", "127.0.0.1")
CLI_SERVER_PORT = int(os.getenv("CLI_SERVER_PORT", "8765"))
CLI_SERVER_BASE_URL = f"http://{CLI_SERVER_HOST}:{CLI_SERVER_PORT}"
CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS = 1
CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS = 2
CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS = 1.0

CLIChannelSender = Literal["ai", "user"]
CLIChannelReader = Literal["ai", "user"]


class ExternalSendMessageRequest(BaseModel):
    """外部聊天服务的消息写入请求体。"""

    sender: CLIChannelSender
    text: str = Field(..., min_length=1)


class ExternalMessage(BaseModel):
    """外部聊天服务返回的消息结构。"""

    id: int = Field(..., ge=1)
    sender: CLIChannelSender
    text: str
    created_at: str


class InMemoryChatStore:
    """最简双对象消息系统：ai、user。"""

    def __init__(self) -> None:
        self._messages: list[ExternalMessage] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._new_message_cond = threading.Condition(self._lock)

    def list_messages(
        self,
        reader: CLIChannelReader,
        after_id: int = 0,
    ) -> list[ExternalMessage]:
        with self._lock:
            return list(self._collect_reader_messages(reader=reader, after_id=after_id))

    def wait_for_reader_messages(
        self,
        reader: CLIChannelReader,
        after_id: int,
        timeout_seconds: float,
    ) -> list[ExternalMessage]:
        """阻塞等待 `reader` 可见的新消息（id > after_id）。"""
        with self._new_message_cond:
            messages = self._collect_reader_messages(reader=reader, after_id=after_id)
            if not messages:
                self._new_message_cond.wait(timeout=timeout_seconds)
                messages = self._collect_reader_messages(reader=reader, after_id=after_id)
            return list(messages)

    @staticmethod
    def _is_visible_to_reader(
        sender: CLIChannelSender,
        reader: CLIChannelReader,
    ) -> bool:
        # 当前策略：任一 reader 均可查看 ai/user 双方完整消息。
        # 保留 reader 参数用于兼容既有 API 与后续扩展。
        _ = sender, reader
        return True

    def _collect_reader_messages(
        self,
        reader: CLIChannelReader,
        after_id: int,
    ) -> list[ExternalMessage]:
        return [
            message
            for message in self._messages
            if message.id > after_id
            and self._is_visible_to_reader(
                sender=message.sender,
                reader=reader,
            )
        ]

    def send_message(
        self,
        sender: CLIChannelSender,
        text: str,
    ) -> ExternalMessage:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text 不能为空")

        with self._lock:
            message = ExternalMessage(
                id=self._next_id,
                sender=sender,
                text=clean_text,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self._messages.append(message)
            self._next_id += 1
            self._new_message_cond.notify_all()

        return message


def build_cli_server_app() -> FastAPI:
    """
    构建外部聊天服务 FastAPI 应用。

    直接运行方式：
    `uv run python .\\cli_server\\cli_server.py`
    """
    app = FastAPI(title="CLI External Chat Server", version="1.0.0")
    store = InMemoryChatStore()

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "cli_external_chat_server"}

    @app.get("/v1/messages", response_model=list[ExternalMessage])
    def list_messages(
        reader: CLIChannelReader = Query(...),
        after_id: int = Query(default=0, ge=0),
    ) -> list[ExternalMessage]:
        return store.list_messages(reader=reader, after_id=after_id)

    @app.get("/v1/events")
    async def stream_events(
        request: Request,
        reader: CLIChannelReader = Query(...),
        after_id: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        """
        SSE 事件流：
        - 推送 `after_id` 之后的新消息（按 message id 递增）
        - 通过 after_id 支持断线续传
        """

        async def _event_generator():
            last_id = after_id
            try:
                while True:
                    if await request.is_disconnected():
                        return

                    try:
                        messages = await asyncio.to_thread(
                            store.wait_for_reader_messages,
                            reader,
                            last_id,
                            CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS,
                        )
                    except asyncio.CancelledError:
                        return
                    except RuntimeError as exc:
                        # uvicorn 关机阶段可能先关闭默认线程池，to_thread 会报此错误。
                        # 这是正常退出路径，直接结束 SSE 生成器即可。
                        if "cannot schedule new futures after shutdown" in str(exc):
                            return
                        raise

                    if not messages:
                        # 保活注释，避免中间层超时断链。
                        yield ": keep-alive\n\n"
                        continue

                    for message in messages:
                        if await request.is_disconnected():
                            return
                        payload = json.dumps(message.model_dump(), ensure_ascii=False)
                        yield (
                            f"id: {message.id}\n"
                            "event: message\n"
                            f"data: {payload}\n\n"
                        )
                        last_id = message.id
            except (asyncio.CancelledError, GeneratorExit):
                return

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/messages", response_model=ExternalMessage, status_code=201)
    def send_message(payload: ExternalSendMessageRequest) -> ExternalMessage:
        try:
            return store.send_message(sender=payload.sender, text=payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def run_cli_server(host: str = CLI_SERVER_HOST, port: int = CLI_SERVER_PORT) -> None:
    uvicorn.run(
        build_cli_server_app(),
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
        timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    )


def main() -> None:
    """直接运行文件即可启动服务。"""
    run_cli_server(host=CLI_SERVER_HOST, port=CLI_SERVER_PORT)


if __name__ == "__main__":
    main()
