from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# cli_server 固定本地通信地址。
CLI_SERVER_HOST = "127.0.0.1"
CLI_SERVER_PORT = 8765
CLI_SERVER_BASE_URL = f"http://{CLI_SERVER_HOST}:{CLI_SERVER_PORT}"
CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS = 1
CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS = 2
CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS = 1.0
CLI_SERVER_STOP_JOIN_TIMEOUT_SECONDS = 1.0
CLI_SERVER_FORCE_EXIT_JOIN_TIMEOUT_SECONDS = 0.5

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
    """
    最简双对象消息系统：
    - 对象：ai、user
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, object]] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._new_message_cond = threading.Condition(self._lock)

    def list_messages(
        self,
        reader: CLIChannelReader,
        after_id: int = 0,
    ) -> list[ExternalMessage]:
        with self._lock:
            raw_messages = [
                message for message in self._messages if int(message["id"]) > after_id
            ]

        return [ExternalMessage.model_validate(item) for item in raw_messages]

    def wait_for_reader_messages(
        self,
        reader: CLIChannelReader,
        after_id: int,
        timeout_seconds: float,
    ) -> list[ExternalMessage]:
        """
        阻塞等待 `reader` 可见的新消息（id > after_id）。
        - reader="ai" 仅接收 sender="user"
        - reader="user" 仅接收 sender="ai"
        """
        with self._new_message_cond:
            raw_messages = self._collect_reader_messages(reader=reader, after_id=after_id)
            if not raw_messages:
                self._new_message_cond.wait(timeout=timeout_seconds)
                raw_messages = self._collect_reader_messages(reader=reader, after_id=after_id)
        return [ExternalMessage.model_validate(item) for item in raw_messages]

    @staticmethod
    def _is_visible_to_reader(
        sender: CLIChannelSender,
        reader: CLIChannelReader,
    ) -> bool:
        return sender != reader

    def _collect_reader_messages(
        self,
        reader: CLIChannelReader,
        after_id: int,
    ) -> list[dict[str, object]]:
        return [
            message
            for message in self._messages
            if int(message["id"]) > after_id
            and self._is_visible_to_reader(
                sender=message["sender"],  # type: ignore[arg-type]
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
            raw_message: dict[str, object] = {
                "id": self._next_id,
                "sender": sender,
                "text": clean_text,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._messages.append(raw_message)
            self._next_id += 1

            self._new_message_cond.notify_all()

        return ExternalMessage.model_validate(raw_message)


def build_cli_server_app() -> FastAPI:
    """
    构建外部聊天服务 FastAPI 应用。

    API 约定：
    - GET  /health
    - GET  /v1/messages?reader=ai|user&after_id=...
    - GET  /v1/events?reader=ai|user&after_id=...
    - POST /v1/messages  body: {sender, text}
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
        - 仅推送对 `reader` 可见的新消息（按 message id 递增）
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


class CLIServerRuntime:
    """封装 uvicorn 服务，供 main.py 以子线程方式启动。"""

    def __init__(
        self,
        host: str = CLI_SERVER_HOST,
        port: int = CLI_SERVER_PORT,
    ) -> None:
        self.host = host
        self.port = port
        self.app = build_cli_server_app()
        self._server = uvicorn.Server(
            uvicorn.Config(
                app=self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
                timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
                timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
            )
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._server.run,
            name="cli-server",
            daemon=True,
        )
        self._thread.start()

        startup_deadline = time.time() + 5.0
        while not self._server.started and time.time() < startup_deadline:
            time.sleep(0.05)

        if not self._server.started:
            raise RuntimeError("cli_server 启动失败")

    def stop(self, wait: bool = True) -> None:
        self._server.should_exit = True
        if wait and self._thread and self._thread.is_alive():
            self._thread.join(timeout=CLI_SERVER_STOP_JOIN_TIMEOUT_SECONDS)
            if self._thread.is_alive():
                # 如果优雅停机仍未完成，触发强制退出，避免长时间阻塞主进程退出。
                self._server.force_exit = True
                self._thread.join(timeout=CLI_SERVER_FORCE_EXIT_JOIN_TIMEOUT_SECONDS)
