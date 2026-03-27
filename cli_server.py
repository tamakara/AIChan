from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# cli_server 固定本地通信地址。
CLI_SERVER_HOST = "127.0.0.1"
CLI_SERVER_PORT = 8765
CLI_SERVER_BASE_URL = f"http://{CLI_SERVER_HOST}:{CLI_SERVER_PORT}"

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


class CLIChannelUnreadStatus(BaseModel):
    """外部聊天服务维护的未读状态。"""

    ai_unread: bool
    user_unread: bool


class InMemoryChatStore:
    """
    最简双对象消息系统：
    - 对象：ai、user
    - 状态：ai_unread、user_unread
    """

    def __init__(self) -> None:
        self._messages: list[dict[str, object]] = []
        self._next_id = 1
        self._unread = {"ai": False, "user": False}
        self._lock = threading.Lock()

    def get_status(self) -> CLIChannelUnreadStatus:
        with self._lock:
            return CLIChannelUnreadStatus(
                ai_unread=self._unread["ai"],
                user_unread=self._unread["user"],
            )

    def list_messages(
        self,
        reader: CLIChannelReader,
        after_id: int = 0,
    ) -> list[ExternalMessage]:
        with self._lock:
            raw_messages = [
                message for message in self._messages if int(message["id"]) > after_id
            ]
            # 调用获取消息接口即视为该对象已读。
            self._unread[reader] = False

        return [ExternalMessage.model_validate(item) for item in raw_messages]

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

            # ai 或 user 任一方发送消息后，两方都标记为有未读。
            self._unread["ai"] = True
            self._unread["user"] = True

        return ExternalMessage.model_validate(raw_message)


def build_cli_server_app() -> FastAPI:
    """
    构建外部聊天服务 FastAPI 应用。

    API 约定：
    - GET  /health
    - GET  /v1/status
    - GET  /v1/messages?reader=ai|user&after_id=...
    - POST /v1/messages  body: {sender, text}
    """
    app = FastAPI(title="CLI External Chat Server", version="1.0.0")
    store = InMemoryChatStore()

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"ok": True, "service": "cli_external_chat_server"}

    @app.get("/v1/status", response_model=CLIChannelUnreadStatus)
    def get_unread_status() -> CLIChannelUnreadStatus:
        return store.get_status()

    @app.get("/v1/messages", response_model=list[ExternalMessage])
    def list_messages(
        reader: CLIChannelReader = Query(...),
        after_id: int = Query(default=0, ge=0),
    ) -> list[ExternalMessage]:
        return store.list_messages(reader=reader, after_id=after_id)

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
                log_level="info",
                access_log=False,
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
            self._thread.join(timeout=3.0)
