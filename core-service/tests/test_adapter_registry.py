from unittest.mock import AsyncMock

import pytest

from core_service.adapters.protocol import AdapterRegistration, Envelope
from core_service.adapters.registry import AdapterConnection, AdapterRegistry
from core_service.adapters.xml_codec import XmlMessageCodec


@pytest.mark.asyncio
async def test_message_query_validates_adapter_xml_and_returns_file_refs() -> None:
    registry = AdapterRegistry(tokens={"qq:main": "secret"}, codec=XmlMessageCodec(), reserved_tool_names=set(), ack_timeout=1, ack_attempts=1, capability_timeout=1)
    registration = AdapterRegistration(adapter_id="qq", instance_id="main", display_name="QQ", file_base_url="http://adapter/files")
    registry._connections[("qq", "main")] = AdapterConnection(registration, object())  # type: ignore[arg-type]
    registry._request_with_retry = AsyncMock(return_value=Envelope(
        type="message.result",
        payload={
            "ok": True,
            "messages_xml": '<messages><message id="1" timestamp="1" sender_id="u"><file ref="old-file" /></message></messages>',
            "next_cursor": "next",
            "has_more": True,
        },
    ))
    result, refs = await registry.query_messages(("qq", "main"), session_id="s", conversation_type="group", conversation_id="1", cursor=None, limit=20)
    assert result.next_cursor == "next" and result.has_more is True
    assert refs == {"old-file"}
    sent = registry._request_with_retry.await_args.args[1]
    assert sent.type == "message.query"
    assert sent.payload["conversation_id"] == "1"
    assert registry.file_source(("qq", "main")) == ("http://adapter/files", "secret")


@pytest.mark.asyncio
async def test_message_query_allows_empty_history() -> None:
    registry = AdapterRegistry(tokens={"qq:main": "secret"}, codec=XmlMessageCodec(), reserved_tool_names=set(), ack_timeout=1, ack_attempts=1, capability_timeout=1)
    registration = AdapterRegistration(adapter_id="qq", instance_id="main", display_name="QQ", file_base_url="http://adapter/files")
    registry._connections[("qq", "main")] = AdapterConnection(registration, object())  # type: ignore[arg-type]
    registry._request_with_retry = AsyncMock(return_value=Envelope(type="message.result", payload={"ok": True, "messages_xml": "<messages />", "next_cursor": None, "has_more": False}))
    result, refs = await registry.query_messages(("qq", "main"), session_id="s", conversation_type="private", conversation_id="1", cursor=None, limit=20)
    assert result.messages_xml == "<messages />" and not refs
