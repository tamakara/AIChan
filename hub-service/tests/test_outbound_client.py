import asyncio

import pytest

from hub_service.services.outbound_client import OutboundClient


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


class DummyHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, json):
        self.calls.append((url, json))
        return self.responses.pop(0)

    async def aclose(self):
        return None


class StubRedisStream:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict]] = []

    async def enqueue_action(self, session_id: str, action: dict) -> None:
        self.actions.append((session_id, action))


def test_create_session_calls_new_endpoint() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"session_id": "agent-1", "metadata": {"session_id": "private_1"}})]
    )

    agent_session_id = asyncio.run(
        client.create_session("private_1", {"session_id": "private_1"})
    )

    assert agent_session_id == "agent-1"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/sessions"
    assert called_payload == {"metadata": {"session_id": "private_1"}}


def test_call_session_uses_text_payload() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    expected_reply = "ok!"
    client._client = DummyHttpClient([DummyResponse({"batch": expected_reply})])  # type: ignore[attr-defined]

    reply = asyncio.run(
        client.call_session("private_1", "agent-1", "hello")
    )

    assert reply == expected_reply
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/chat"
    assert called_payload == {"session_id": "agent-1", "batch": "hello"}


def test_call_session_invalid_response_raises() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient([DummyResponse({"bad": "shape"})])  # type: ignore[attr-defined]

    with pytest.raises(Exception):
        asyncio.run(client.call_session("private_1", "agent-1", "hello"))


def test_send_reply_enqueues_action() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private_1", "hello!"))

    assert len(redis_stream.actions) == 1
    sid, action = redis_stream.actions[0]
    assert sid == "private_1"
    assert action == {"type": "message", "session_id": "private_1", "content": "hello!"}
