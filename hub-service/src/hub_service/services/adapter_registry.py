from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from fastapi import WebSocket
from jsonschema import validate

from .internal_clients import SkillServiceClient
from .protocol import AdapterRegistration, Envelope, PublishedEvent

EventHandler = Callable[[tuple[str, str], PublishedEvent], Awaitable[None]]


@dataclass
class AdapterConnection:
    registration: AdapterRegistration
    websocket: WebSocket
    pending: dict[str, asyncio.Future[Envelope]] = field(default_factory=dict)
    seen_events: set[str] = field(default_factory=set)


class AdapterRegistry:
    """管理适配器长连接和关联 RPC；所有等待状态都限定在当前进程生命周期内。"""

    def __init__(
        self, tokens: dict[str, str], skill_client: SkillServiceClient,
        ack_timeout: float, ack_attempts: int, capability_timeout: float,
    ) -> None:
        self._tokens = tokens
        self._skill_client = skill_client
        self._ack_timeout = ack_timeout
        self._ack_attempts = ack_attempts
        self._capability_timeout = capability_timeout
        self._connections: dict[tuple[str, str], AdapterConnection] = {}
        self._event_handler: EventHandler | None = None
        self._lock = asyncio.Lock()

    def set_event_handler(self, handler: EventHandler) -> None:
        self._event_handler = handler

    def token_allowed(self, token: str) -> bool:
        return bool(token) and token in self._tokens.values()

    async def handle(self, websocket: WebSocket, token: str) -> None:
        await websocket.accept()
        connection: AdapterConnection | None = None
        key: tuple[str, str] | None = None
        try:
            first = Envelope.model_validate(await websocket.receive_json())
            if first.type != "adapter.register":
                raise ValueError("first message must be adapter.register")
            registration = AdapterRegistration.model_validate(first.payload)
            key = (registration.adapter_id, registration.instance_id)
            if self._tokens.get(f"{key[0]}:{key[1]}") != token:
                raise PermissionError("adapter identity does not match token")
            connection = AdapterConnection(registration=registration, websocket=websocket)
            await self._skill_client.register(registration)
            async with self._lock:
                old = self._connections.get(key)
                self._connections[key] = connection
            if old is not None:
                await old.websocket.close(code=4001, reason="replaced by newer connection")
            await websocket.send_json(Envelope(type="adapter.registered", correlation_id=first.id, payload={"accepted": True}).model_dump())

            while True:
                envelope = Envelope.model_validate(await websocket.receive_json())
                try:
                    await self._receive(key, connection, envelope)
                except ValueError as exc:
                    await websocket.send_json(Envelope(
                        type="protocol.error", correlation_id=envelope.id,
                        payload={"error": str(exc)},
                    ).model_dump())
        finally:
            if key is not None and connection is not None:
                removed_current = False
                async with self._lock:
                    if self._connections.get(key) is connection:
                        self._connections.pop(key, None)
                        removed_current = True
                if removed_current:
                    try:
                        await self._skill_client.deactivate(*key)
                    except Exception:
                        # 断线收口不能被 skill-service 的短暂故障反向阻塞。
                        pass

    async def _receive(self, key: tuple[str, str], connection: AdapterConnection, envelope: Envelope) -> None:
        if envelope.type == "heartbeat.ping":
            await connection.websocket.send_json(Envelope(
                type="heartbeat.pong", correlation_id=envelope.id, payload={}
            ).model_dump())
            return
        if envelope.type in {"reply.ack", "capability.result"} and envelope.correlation_id:
            pending = connection.pending.get(envelope.correlation_id)
            if pending is not None and not pending.done():
                pending.set_result(envelope)
            return
        if envelope.type != "event.publish":
            return
        event = PublishedEvent.model_validate(envelope.payload)
        _validate_xml(event.input_xml, connection.registration, direction="input")
        duplicate = event.event_id in connection.seen_events
        if not duplicate:
            connection.seen_events.add(event.event_id)
            if len(connection.seen_events) > 4096:
                connection.seen_events.clear()
                connection.seen_events.add(event.event_id)
            if self._event_handler is not None:
                await self._event_handler(key, event)
        await connection.websocket.send_json(Envelope(
            type="event.ack", correlation_id=envelope.id, payload={"event_id": event.event_id, "duplicate": duplicate}
        ).model_dump())

    async def deliver_reply(self, key: tuple[str, str], session_id: str, output_xml: str) -> None:
        connection = self._connections.get(key)
        if connection is None:
            raise RuntimeError("adapter offline")
        _validate_xml(output_xml, connection.registration, direction="output")
        result = await self._request_with_retry(key, Envelope(type="reply.deliver", payload={
            "command_id": str(uuid4()), "session_id": session_id, "output_xml": output_xml,
        }), self._ack_timeout, self._ack_attempts)
        if not result.payload.get("ok", False):
            raise RuntimeError(str(result.payload.get("error", "adapter rejected reply")))

    async def invoke(self, session_key: tuple[str, str], session_id: str, capability: str, arguments: dict[str, Any]) -> Any:
        connection = self._connections.get(session_key)
        if connection is None:
            raise RuntimeError("adapter offline")
        if capability not in {item.name for item in connection.registration.capabilities}:
            raise ValueError("capability is not declared by adapter")
        result = await self._request_with_retry(session_key, Envelope(type="capability.invoke", payload={
            "session_id": session_id, "capability": capability, "arguments": arguments,
        }), self._capability_timeout, 1)
        if not result.payload.get("ok", False):
            raise RuntimeError(str(result.payload.get("error", "adapter capability failed")))
        return result.payload.get("result")

    async def _request_with_retry(self, key: tuple[str, str], envelope: Envelope, timeout: float, attempts: int) -> Envelope:
        last_error: Exception | None = None
        for _ in range(attempts):
            connection = self._connections.get(key)
            if connection is None:
                raise RuntimeError("adapter offline")
            future = asyncio.get_running_loop().create_future()
            connection.pending[envelope.id] = future
            try:
                await connection.websocket.send_json(envelope.model_dump())
                return await asyncio.wait_for(future, timeout)
            except Exception as exc:
                last_error = exc
            finally:
                connection.pending.pop(envelope.id, None)
        raise RuntimeError("adapter request acknowledgement timed out") from last_error

    def status(self) -> list[dict[str, Any]]:
        statuses: list[dict[str, Any]] = []
        for identity in self._tokens:
            adapter_id, instance_id = identity.split(":", 1)
            connection = self._connections.get((adapter_id, instance_id))
            statuses.append({
                "adapter_id": adapter_id,
                "instance_id": instance_id,
                "online": connection is not None,
                "display_name": connection.registration.display_name if connection else None,
                "capabilities": [item.name for item in connection.registration.capabilities] if connection else [],
            })
        return statuses


def _validate_xml(raw: str, registration: AdapterRegistration, direction: str) -> None:
    root = ElementTree.fromstring(raw)
    expected_root = "messages" if direction == "input" else "reply"
    if root.tag != expected_root:
        raise ValueError(f"{direction} XML root must be <{expected_root}>")
    base_nodes = {"text", "image", "file", "audio", "video", "mention", "quote", "extension"}
    declared = {
        (item.namespace, item.name): item for item in registration.extensions if direction in item.directions
    }
    for message in list(root):
        if message.tag != "message":
            raise ValueError(f"{expected_root} only accepts <message>")
        for child in list(message):
            if child.tag not in base_nodes:
                raise ValueError(f"unsupported protocol node: {child.tag}")
            if child.tag != "extension":
                continue
            definition = declared.get((child.get("namespace", ""), child.get("name", "")))
            if definition is None:
                raise ValueError("adapter extension is not declared for this direction")
            params: dict[str, str] = {}
            for param in list(child):
                if param.tag != "param" or not param.get("name"):
                    raise ValueError("extension only accepts named param nodes")
                params[str(param.get("name"))] = param.text or ""
            validate(params, definition.parameters_schema or {"type": "object"})
