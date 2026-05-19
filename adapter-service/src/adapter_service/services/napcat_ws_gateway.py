from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..logger import elapsed_ms, get_logger, log_info, log_warning, start_timer
from .adapter_service import AdapterService
from .redis_stream import AdapterRedisStream
from .stream_models import EventStreamMessage


class NapcatWsGateway:
    def __init__(
        self,
        adapter_service: AdapterService,
        redis_stream: AdapterRedisStream,
        action_timeout_seconds: float,
    ) -> None:
        self._logger = get_logger("napcat_ws_gateway")
        self._adapter_service = adapter_service
        self._redis_stream = redis_stream
        self._action_timeout_seconds = action_timeout_seconds
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = asyncio.Lock()

    async def handle_connection(self, websocket: WebSocket) -> None:
        await websocket.accept()
        log_info(self._logger, "adapter.ws_connected")

        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue

                if self._is_event(message):
                    await self._handle_event(message)
                    continue

                if self._is_action_response(message):
                    await self._resolve_action(message)
                    continue
        except WebSocketDisconnect:
            return
        finally:
            log_info(self._logger, "adapter.ws_disconnected")

    async def send_action(self, websocket: WebSocket, action: str, params: dict[str, Any]) -> dict[str, Any]:
        started_at = start_timer()
        echo = str(uuid.uuid4())
        request = {
            "action": action,
            "params": params,
            "echo": echo,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async with self._pending_lock:
            self._pending_actions[echo] = future

        try:
            await websocket.send_json(request)
            result = await asyncio.wait_for(future, timeout=self._action_timeout_seconds)
            log_info(
                self._logger,
                "adapter.ws_action_completed",
                action_type=action,
                status=result.get("status", "unknown"),
                elapsed_ms=elapsed_ms(started_at),
            )
            return result
        except TimeoutError:
            log_warning(
                self._logger,
                "adapter.ws_action_timeout",
                action_type=action,
                elapsed_ms=elapsed_ms(started_at),
            )
            raise
        finally:
            async with self._pending_lock:
                self._pending_actions.pop(echo, None)

    async def _handle_event(self, raw_event: dict[str, Any]) -> None:
        clean_result = self._adapter_service.clean_event(raw_event)
        if not clean_result.accepted:
            return

        assert clean_result.payload is not None
        # 适配层不维护业务态，只负责把标准化事件投递到队列供 hub 统一调度。
        await self._redis_stream.publish_event(
            EventStreamMessage.from_filtered_event(clean_result.payload)
        )

    async def _resolve_action(self, response: dict[str, Any]) -> None:
        echo = str(response.get("echo", ""))
        if not echo:
            return

        async with self._pending_lock:
            future = self._pending_actions.get(echo)

        if future is not None and not future.done():
            future.set_result(response)

    @staticmethod
    def _is_event(message: dict[str, Any]) -> bool:
        return "post_type" in message

    @staticmethod
    def _is_action_response(message: dict[str, Any]) -> bool:
        return "echo" in message and "status" in message and "retcode" in message


