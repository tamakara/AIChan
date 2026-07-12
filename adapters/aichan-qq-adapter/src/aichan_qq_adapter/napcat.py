from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class NapcatGateway:
    def __init__(self, action_timeout: float, on_event: EventHandler | None = None) -> None:
        self._timeout = action_timeout
        self._on_event = on_event
        self._websocket: WebSocket | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()

    def set_event_handler(self, handler: EventHandler) -> None:
        self._on_event = handler

    async def handle(self, websocket: WebSocket) -> None:
        await websocket.accept()
        previous = self._websocket
        self._websocket = websocket
        if previous is not None:
            await previous.close(code=4001, reason="replaced")
        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue
                echo = str(message.get("echo", ""))
                if echo and echo in self._pending:
                    future = self._pending[echo]
                    if not future.done():
                        future.set_result(message)
                elif "post_type" in message and self._on_event is not None:
                    await self._on_event(message)
        except WebSocketDisconnect:
            return
        finally:
            if self._websocket is websocket:
                self._websocket = None

    async def action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._websocket is None:
            raise RuntimeError("NapCat is offline")
        echo = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        try:
            async with self._send_lock:
                await self._websocket.send_json({"action": action, "params": params, "echo": echo})
            return await asyncio.wait_for(future, self._timeout)
        finally:
            self._pending.pop(echo, None)

    @property
    def connected(self) -> bool:
        return self._websocket is not None


def message_segments(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def is_at_bot(event: dict[str, Any]) -> bool:
    self_id = str(event.get("self_id", ""))
    return any(
        segment.get("type") == "at" and str(segment.get("data", {}).get("qq", "")) == self_id
        for segment in message_segments(event.get("message"))
        if isinstance(segment.get("data"), dict)
    )
