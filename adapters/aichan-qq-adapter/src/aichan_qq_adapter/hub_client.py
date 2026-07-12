from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import websockets

ReplyHandler = Callable[[dict[str, Any]], Awaitable[None]]
CapabilityHandler = Callable[[str, dict[str, Any]], Awaitable[Any]]


class HubClient:
    def __init__(
        self, ws_url: str, token: str, registration: dict[str, Any],
        reply_handler: ReplyHandler, capability_handler: CapabilityHandler,
        ack_timeout: float, reconnect_seconds: float,
    ) -> None:
        self._url = ws_url
        self._token = token
        self._registration = registration
        self._reply_handler = reply_handler
        self._capability_handler = capability_handler
        self._ack_timeout = ack_timeout
        self._reconnect_seconds = reconnect_seconds
        self._websocket: Any = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self._stopping = False

    async def run(self) -> None:
        while not self._stopping:
            try:
                async with websockets.connect(
                    self._url, additional_headers={"Authorization": f"Bearer {self._token}"},
                    max_size=1024 * 1024,
                ) as websocket:
                    self._websocket = websocket
                    registration_id = str(uuid4())
                    await self._send({
                        "version": "1.0", "type": "adapter.register", "id": registration_id,
                        "correlation_id": None, "payload": self._registration,
                    })
                    first = await websocket.recv()
                    import json
                    registered = json.loads(first)
                    if registered.get("type") != "adapter.registered":
                        raise RuntimeError("hub rejected adapter registration")
                    heartbeat = asyncio.create_task(self._heartbeat_loop())
                    try:
                        await self._receive_loop(websocket)
                    finally:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
            except asyncio.CancelledError:
                return
            except Exception:
                self._fail_pending()
                await asyncio.sleep(self._reconnect_seconds)
            finally:
                self._websocket = None

    async def publish(self, payload: dict[str, Any]) -> None:
        envelope = {
            "version": "1.0", "type": "event.publish", "id": str(uuid4()),
            "correlation_id": None, "payload": payload,
        }
        last_error: Exception | None = None
        for _ in range(3):
            try:
                await self._request(envelope)
                return
            except Exception as exc:
                last_error = exc
        raise RuntimeError("hub did not acknowledge event") from last_error

    async def _receive_loop(self, websocket: Any) -> None:
        import json
        async for raw in websocket:
            envelope = json.loads(raw)
            correlation_id = envelope.get("correlation_id")
            if correlation_id in self._pending:
                future = self._pending[correlation_id]
                if not future.done():
                    future.set_result(envelope)
                continue
            if envelope.get("type") == "heartbeat.ping":
                await self._respond("heartbeat.pong", envelope, {})
            elif envelope.get("type") == "reply.deliver":
                try:
                    await self._reply_handler(dict(envelope.get("payload", {})))
                    payload = {"ok": True}
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc)}
                await self._respond("reply.ack", envelope, payload)
            elif envelope.get("type") == "capability.invoke":
                request = dict(envelope.get("payload", {}))
                try:
                    result = await self._capability_handler(str(request.get("capability", "")), dict(request.get("arguments", {})))
                    payload = {"ok": True, "result": result}
                except Exception as exc:
                    payload = {"ok": False, "error": str(exc)}
                await self._respond("capability.result", envelope, payload)

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            await self._send({
                "version": "1.0", "type": "heartbeat.ping", "id": str(uuid4()),
                "correlation_id": None, "payload": {},
            })

    async def _respond(self, message_type: str, request: dict[str, Any], payload: dict[str, Any]) -> None:
        await self._send({
            "version": "1.0", "type": message_type, "id": str(uuid4()),
            "correlation_id": request.get("id"), "payload": payload,
        })

    async def _request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if self._websocket is None:
            raise RuntimeError("hub is offline")
        future = asyncio.get_running_loop().create_future()
        self._pending[str(envelope["id"])] = future
        try:
            await self._send(envelope)
            return await asyncio.wait_for(future, self._ack_timeout)
        finally:
            self._pending.pop(str(envelope["id"]), None)

    async def _send(self, envelope: dict[str, Any]) -> None:
        if self._websocket is None:
            raise RuntimeError("hub is offline")
        import json
        async with self._send_lock:
            await self._websocket.send(json.dumps(envelope, ensure_ascii=False))

    def _fail_pending(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(RuntimeError("hub disconnected"))
        self._pending.clear()

    async def stop(self) -> None:
        self._stopping = True
        if self._websocket is not None:
            await self._websocket.close()
