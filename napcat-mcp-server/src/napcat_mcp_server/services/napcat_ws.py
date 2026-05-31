from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..logger import elapsed_ms, get_logger, log_info, log_warning, start_timer


class NapcatWsGateway:
    """NapCat 反向 WebSocket 处理器 — 只做动作发送/响应，不处理事件。"""

    def __init__(self, action_timeout_seconds: float) -> None:
        self._logger = get_logger("ws_gateway")
        self._action_timeout_seconds = action_timeout_seconds
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = asyncio.Lock()

    async def handle_connection(self, websocket: WebSocket) -> None:
        await websocket.accept()
        log_info(self._logger, "napcat_mcp.ws_connected")

        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue

                # 只关心动作响应（有 echo + status/retcode），忽略事件
                if _is_action_response(message):
                    await self._resolve_action(message)
        except WebSocketDisconnect:
            return
        finally:
            log_info(self._logger, "napcat_mcp.ws_disconnected")

    async def send_action(self, websocket: WebSocket, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """发送 OneBot 动作并等待 echo 响应。"""
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
                "napcat_mcp.ws_action_completed",
                action_type=action,
                status=result.get("status", "unknown"),
                elapsed_ms=elapsed_ms(started_at),
            )
            return result
        except TimeoutError:
            log_warning(
                self._logger,
                "napcat_mcp.ws_action_timeout",
                action_type=action,
                elapsed_ms=elapsed_ms(started_at),
            )
            raise
        finally:
            async with self._pending_lock:
                self._pending_actions.pop(echo, None)

    async def _resolve_action(self, response: dict[str, Any]) -> None:
        echo = str(response.get("echo", ""))
        if not echo:
            return

        async with self._pending_lock:
            future = self._pending_actions.get(echo)

        if future is not None and not future.done():
            future.set_result(response)


def _is_action_response(message: dict[str, Any]) -> bool:
    return "echo" in message and "status" in message and "retcode" in message
