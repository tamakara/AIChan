import asyncio

import pytest

from hub_service.router.schemas import AgentInboundMessage
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
        self.actions: list[tuple[str, str]] = []

    async def enqueue_send_message(self, session_id: str, content: str) -> None:
        self.actions.append((session_id, content))


def test_create_agent_calls_new_endpoint() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"agent_id": "agent-1", "metadata": {"session_id": "private_1"}})]
    )

    created_agent_id = asyncio.run(client.create_agent("private_1", {"session_id": "private_1"}))

    assert created_agent_id == "agent-1"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/agents"
    assert called_payload == {"metadata": {"session_id": "private_1"}}


def test_call_agent_uses_slim_messages_payload() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient([DummyResponse({"reply": "ok"})])  # type: ignore[attr-defined]

    reply = asyncio.run(
        client.call_agent(
            "private_1",
            "agent-1",
            [
                AgentInboundMessage(
                    user_id="qq_1",
                    content="hello",
                    event_time="1710000000",
                )
            ],
        )
    )

    assert reply == "ok"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/chat"
    assert called_payload == {
        "agent_id": "agent-1",
        "messages": [{"user_id": "qq_1", "content": "hello", "event_time": "1710000000"}],
    }


def test_call_agent_invalid_response_raises() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient([DummyResponse({"bad": "shape"})])  # type: ignore[attr-defined]

    with pytest.raises(Exception):
        asyncio.run(
            client.call_agent(
                "private_1",
                "agent-1",
                [
                    AgentInboundMessage(
                        user_id="qq_1",
                        content="hello",
                        event_time="1710000000",
                    )
                ],
            )
        )


def test_send_reply_enqueue_action() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private_1", "ok"))

    assert redis_stream.actions == [("private_1", "ok")]
