from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from jsonschema import validate

from .protocol import AdapterRegistration, Envelope, MessageQueryResult, PublishedEvent
from .xml_codec import XmlMessageCodec

EventHandler = Callable[[tuple[str, str], PublishedEvent, frozenset[str]], Awaitable[None]]


@dataclass
class AdapterConnection:
    registration: AdapterRegistration
    websocket: WebSocket
    pending: dict[str, asyncio.Future[Envelope]] = field(default_factory=dict)
    seen_events: set[str] = field(default_factory=set)


class AdapterRegistry:
    def __init__(self, *, tokens: dict[str, str], codec: XmlMessageCodec, reserved_tool_names: set[str], ack_timeout: float, ack_attempts: int, capability_timeout: float) -> None:
        self._tokens = tokens
        self._codec = codec
        self._reserved_tool_names = reserved_tool_names
        self._ack_timeout = ack_timeout
        self._ack_attempts = ack_attempts
        self._capability_timeout = capability_timeout
        self._connections: dict[tuple[str, str], AdapterConnection] = {}
        self._event_handler: EventHandler | None = None
        self._lock = asyncio.Lock()

    def set_event_handler(self, handler: EventHandler) -> None:
        self._event_handler = handler

    def set_reserved_tool_names(self, names: set[str]) -> None:
        self._reserved_tool_names = set(names)

    def token_allowed(self, token: str) -> bool:
        return bool(token) and token in self._tokens.values()

    async def handle(self, websocket: WebSocket, token: str) -> None:
        await websocket.accept()
        connection: AdapterConnection | None = None
        key: tuple[str, str] | None = None
        try:
            first = Envelope.model_validate(await websocket.receive_json())
            if first.type != "adapter.register":
                raise ValueError("首条消息必须是 adapter.register")
            registration = AdapterRegistration.model_validate(first.payload)
            key = (registration.adapter_id, registration.instance_id)
            if self._tokens.get(f"{key[0]}:{key[1]}") != token:
                raise PermissionError("adapter identity does not match token")
            collisions = {item.tool_name for item in registration.capabilities} & self._reserved_tool_names
            if collisions:
                raise ValueError(f"adapter capability 工具名冲突: {sorted(collisions)[0]}")
            connection = AdapterConnection(registration, websocket)
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
                    await websocket.send_json(Envelope(type="protocol.error", correlation_id=envelope.id, payload={"error": str(exc)}).model_dump())
        finally:
            if key is not None and connection is not None:
                async with self._lock:
                    if self._connections.get(key) is connection:
                        self._connections.pop(key, None)

    async def _receive(self, key: tuple[str, str], connection: AdapterConnection, envelope: Envelope) -> None:
        if envelope.type == "heartbeat.ping":
            await connection.websocket.send_json(Envelope(type="heartbeat.pong", correlation_id=envelope.id).model_dump())
            return
        if envelope.type in {"reply.ack", "capability.result", "message.result"} and envelope.correlation_id:
            future = connection.pending.get(envelope.correlation_id)
            if future is not None and not future.done():
                future.set_result(envelope)
            return
        if envelope.type != "event.publish":
            raise ValueError(f"不支持的消息类型: {envelope.type}")
        event = PublishedEvent.model_validate(envelope.payload)
        parsed = self._codec.validate_messages(event.messages_xml, connection.registration)
        duplicate = event.event_id in connection.seen_events
        if not duplicate:
            connection.seen_events.add(event.event_id)
            if len(connection.seen_events) > 4096:
                connection.seen_events = {event.event_id}
            if self._event_handler is not None:
                await self._event_handler(key, event.model_copy(update={"messages_xml": parsed.xml}), parsed.file_refs)
        await connection.websocket.send_json(Envelope(type="event.ack", correlation_id=envelope.id, payload={"event_id": event.event_id, "duplicate": duplicate}).model_dump())

    async def deliver_reply(self, key: tuple[str, str], session_id: str, reply_xml: str, allowed_file_refs: frozenset[str]) -> None:
        connection = self._require_connection(key)
        parsed = self._codec.validate_reply(reply_xml, connection.registration, allowed_file_refs)
        result = await self._request_with_retry(key, Envelope(type="reply.deliver", payload={"command_id": str(uuid4()), "session_id": session_id, "reply_xml": parsed.xml}), self._ack_timeout, self._ack_attempts)
        if not result.payload.get("ok", False):
            raise RuntimeError(str(result.payload.get("error", "adapter rejected reply")))

    async def invoke(self, key: tuple[str, str], session_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        connection = self._require_connection(key)
        capability = next((item for item in connection.registration.capabilities if item.tool_name == tool_name), None)
        if capability is None:
            raise ValueError("capability is not declared by adapter")
        validate(arguments, capability.input_schema)
        result = await self._request_with_retry(key, Envelope(type="capability.invoke", payload={"session_id": session_id, "capability": capability.name, "arguments": arguments}), self._capability_timeout, 1)
        if not result.payload.get("ok", False):
            raise RuntimeError(str(result.payload.get("error", "adapter capability failed")))
        value = result.payload.get("result")
        if capability.output_schema:
            validate(value, capability.output_schema)
        return value

    async def query_messages(
        self,
        key: tuple[str, str],
        *,
        session_id: str,
        conversation_type: str,
        conversation_id: str,
        cursor: str | None,
        limit: int,
    ) -> tuple[MessageQueryResult, frozenset[str]]:
        connection = self._require_connection(key)
        result = await self._request_with_retry(
            key,
            Envelope(
                type="message.query",
                payload={
                    "session_id": session_id,
                    "conversation_type": conversation_type,
                    "conversation_id": conversation_id,
                    "cursor": cursor,
                    "limit": limit,
                },
            ),
            self._capability_timeout,
            1,
        )
        if not result.payload.get("ok", False):
            raise RuntimeError(str(result.payload.get("error", "adapter message query failed")))
        query = MessageQueryResult.model_validate({
            "messages_xml": result.payload.get("messages_xml"),
            "next_cursor": result.payload.get("next_cursor"),
            "has_more": result.payload.get("has_more", False),
        })
        parsed = self._codec.validate_messages(query.messages_xml, connection.registration, allow_empty=True)
        return query.model_copy(update={"messages_xml": parsed.xml}), parsed.file_refs

    def file_source(self, key: tuple[str, str]) -> tuple[str, str]:
        registration = self.registration(key)
        token = self._tokens.get(f"{key[0]}:{key[1]}")
        if not token:
            raise RuntimeError("adapter token not found")
        return registration.file_base_url.rstrip("/"), token

    def registration(self, key: tuple[str, str]) -> AdapterRegistration:
        return self._require_connection(key).registration

    def tool_schemas(self, key: tuple[str, str]) -> list[dict[str, Any]]:
        return [{"type": "function", "function": {"name": item.tool_name, "description": item.description, "parameters": item.input_schema}} for item in self.registration(key).capabilities]

    async def _request_with_retry(self, key: tuple[str, str], envelope: Envelope, timeout: float, attempts: int) -> Envelope:
        last_error: Exception | None = None
        for _ in range(attempts):
            connection = self._require_connection(key)
            future: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
            connection.pending[envelope.id] = future
            try:
                await connection.websocket.send_json(envelope.model_dump())
                return await asyncio.wait_for(future, timeout)
            except Exception as exc:
                last_error = exc
            finally:
                connection.pending.pop(envelope.id, None)
        raise RuntimeError("adapter request acknowledgement timed out") from last_error

    def _require_connection(self, key: tuple[str, str]) -> AdapterConnection:
        connection = self._connections.get(key)
        if connection is None:
            raise RuntimeError("adapter offline")
        return connection

    def status(self) -> list[dict[str, Any]]:
        result = []
        for identity in self._tokens:
            adapter_id, instance_id = identity.split(":", 1)
            connection = self._connections.get((adapter_id, instance_id))
            result.append({"adapter_id": adapter_id, "instance_id": instance_id, "online": connection is not None, "display_name": connection.registration.display_name if connection else None, "capabilities": [item.name for item in connection.registration.capabilities] if connection else []})
        return result
