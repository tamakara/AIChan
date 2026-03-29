from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

CLI_SERVER_HOST = os.getenv("CLI_SERVER_HOST", "127.0.0.1")
CLI_SERVER_PORT = int(os.getenv("CLI_SERVER_PORT", "8765"))
CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS = 1
CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS = 2
CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS = 1.0
REGISTRY_RETRY_SECONDS = 3
DEFAULT_AICHAN_REGISTRY_URL = "http://127.0.0.1:8000/internal/registry/register"
AICHAN_REGISTRY_URL = os.getenv("AICHAN_REGISTRY_URL", DEFAULT_AICHAN_REGISTRY_URL)
CLI_GATEWAY_BASE_HOST = os.getenv("CLI_GATEWAY_BASE_HOST", "127.0.0.1")

CLIChannelIdentity = Literal["ai", "user"]


class ExternalSendMessageRequest(BaseModel):
    sender: CLIChannelIdentity
    text: str = Field(..., min_length=1)


class ExternalMessage(BaseModel):
    id: int = Field(..., ge=1)
    sender: CLIChannelIdentity
    text: str
    created_at: str


class InMemoryChatStore:
    """
    最小内存消息存储。

    该存储同时服务于：
    1. HTTP 拉取消息接口；
    2. SSE 实时事件推送接口。
    """

    def __init__(self) -> None:
        self._messages: list[ExternalMessage] = []
        self._next_id = 1
        self._lock = threading.Lock()
        self._new_message_cond = threading.Condition(self._lock)

    def list_messages(self, after_id: int = 0) -> list[ExternalMessage]:
        with self._lock:
            return list(self._collect_messages(after_id=after_id))

    def wait_for_messages(
        self,
        after_id: int,
        timeout_seconds: float,
    ) -> list[ExternalMessage]:
        with self._new_message_cond:
            messages = self._collect_messages(after_id=after_id)
            if not messages:
                self._new_message_cond.wait(timeout=timeout_seconds)
                messages = self._collect_messages(after_id=after_id)
            return list(messages)

    def _collect_messages(self, after_id: int) -> list[ExternalMessage]:
        return [message for message in self._messages if message.id > after_id]

    def send_message(self, sender: CLIChannelIdentity, text: str) -> ExternalMessage:
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


def _build_registry_payload() -> dict[str, Any]:
    """
    构建 CLI 网关注册载荷。

    当前网关是消息通道类型，必须显式声明 `type=channel`。
    """
    return {
        "name": "cli",
        "type": "channel",
        "base_url": f"http://{CLI_GATEWAY_BASE_HOST}:{CLI_SERVER_PORT}",
        "openapi_path": "/openapi.json",
        "sse_path": "/v1/events",
    }


async def register_to_registry_loop() -> None:
    """
    后台注册重试循环。

    只要注册中心不可达或返回失败，就每 3 秒重试一次；
    一旦成功即退出，不影响网关 HTTP 服务对外提供能力。
    """
    payload = _build_registry_payload()
    while True:
        try:
            logger.info(
                "🔌 [CLIGateway] 尝试注册到大脑，url='{}'，payload={}",
                AICHAN_REGISTRY_URL,
                payload,
            )
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(AICHAN_REGISTRY_URL, json=payload)
                response.raise_for_status()
            logger.info("✅ [CLIGateway] 接入大脑成功，status_code={}", response.status_code)
            return
        except asyncio.CancelledError:
            logger.info("🛑 [CLIGateway] 注册任务收到取消信号，结束后台注册")
            raise
        except Exception as exc:
            logger.error(
                "❌ [CLIGateway] 注册失败，error='{}'，{} 秒后重试",
                exc,
                REGISTRY_RETRY_SECONDS,
            )
            await asyncio.sleep(REGISTRY_RETRY_SECONDS)


@asynccontextmanager
async def gateway_lifespan(app: FastAPI):
    """
    网关生命周期管理。

    启动阶段创建后台注册任务，关闭阶段取消并等待任务退出。
    """
    logger.info("🚀 [CLIGateway] 启动中，注册任务将在后台执行（非阻塞）")
    registration_task = asyncio.create_task(
        register_to_registry_loop(),
        name="cli-gateway-registry-registration",
    )
    app.state.registration_task = registration_task
    try:
        yield
    finally:
        logger.info("🛑 [CLIGateway] 服务关闭中，停止注册后台任务")
        registration_task.cancel()
        with suppress(asyncio.CancelledError):
            await registration_task


def build_cli_gateway_app() -> FastAPI:
    """构建 CLI 网关 FastAPI 应用。"""
    app = FastAPI(
        title="CLI Gateway Server",
        version="2.0.0",
        lifespan=gateway_lifespan,
    )
    store = InMemoryChatStore()

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"ok": True, "service": "cli_gateway"}

    @app.get("/v1/messages", response_model=list[ExternalMessage])
    async def list_messages(after_id: int = Query(default=0, ge=0)) -> list[ExternalMessage]:
        return store.list_messages(after_id=after_id)

    @app.get("/v1/events")
    async def stream_events(
        request: Request,
        after_id: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        """
        统一 SSE 事件流。

        行为说明：
        1. 不再区分 reader；
        2. 推送 `after_id` 之后的新消息；
        3. 在无新消息时发送 keep-alive 保活注释。
        """

        async def _event_generator():
            last_id = after_id
            logger.info("📡 [CLIGateway] SSE 客户端已连接，after_id={}", after_id)
            try:
                while True:
                    if await request.is_disconnected():
                        logger.info("📡 [CLIGateway] SSE 客户端断开连接")
                        return

                    try:
                        messages = await asyncio.to_thread(
                            store.wait_for_messages,
                            last_id,
                            CLI_SERVER_SSE_WAIT_TIMEOUT_SECONDS,
                        )
                    except asyncio.CancelledError:
                        return
                    except RuntimeError as exc:
                        if "cannot schedule new futures after shutdown" in str(exc):
                            return
                        raise

                    if not messages:
                        yield ": keep-alive\n\n"
                        continue

                    for message in messages:
                        if await request.is_disconnected():
                            return
                        payload = json.dumps(message.model_dump(), ensure_ascii=False)
                        logger.info("📡 [CLIGateway] 推送 SSE 消息，message_id={}", message.id)
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
    async def send_message(payload: ExternalSendMessageRequest) -> ExternalMessage:
        try:
            message = store.send_message(sender=payload.sender, text=payload.text)
            logger.info(
                "✅ [CLIGateway] 收到消息写入，message_id={}，sender='{}'",
                message.id,
                message.sender,
            )
            return message
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def run_cli_gateway(host: str = CLI_SERVER_HOST, port: int = CLI_SERVER_PORT) -> None:
    """运行 CLI 网关服务。"""
    logger.info("🚀 [CLIGateway] HTTP 服务启动，host='{}'，port={}", host, port)
    uvicorn.run(
        build_cli_gateway_app(),
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
        timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    )


def main() -> None:
    """程序入口。"""
    run_cli_gateway(host=CLI_SERVER_HOST, port=CLI_SERVER_PORT)


if __name__ == "__main__":
    main()
