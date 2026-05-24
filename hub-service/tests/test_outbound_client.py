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
        self.actions: list[tuple[str, str]] = []

    async def enqueue_action_xml(self, session_id: str, action_xml: str) -> None:
        self.actions.append((session_id, action_xml))


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


def test_call_agent_uses_batch_payload() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )
    expected_batch = '<batch type="end"><message session_id="private_1">ok</message></batch>'
    client._client = DummyHttpClient([DummyResponse({"batch": expected_batch})])  # type: ignore[attr-defined]

    batch = asyncio.run(
        client.call_agent(
            "private_1",
            "agent-1",
            '<batch type="start"><message message_type="private" sub_type="friend" '
            'message_id="11" session_id="private_1" user_id="qq_1" '
            'time="1710000000">hello</message></batch>',
        )
    )

    assert batch == expected_batch
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/chat"
    assert called_payload == {
        "agent_id": "agent-1",
        "batch": '<batch type="start"><message message_type="private" sub_type="friend" '
        'message_id="11" session_id="private_1" user_id="qq_1" '
        'time="1710000000">hello</message></batch>',
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
                '<batch type="append"><message message_type="private" sub_type="friend" '
                'message_id="11" session_id="private_1" user_id="qq_1" '
                'time="1710000000">hello</message></batch>',
            )
        )


def test_send_actions_enqueue_action_xmls() -> None:
    redis_stream = StubRedisStream()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        redis_stream=redis_stream,  # type: ignore[arg-type]
    )

    asyncio.run(
        client.send_actions(
            "private_1",
            '<batch type="end"><message session_id="private_1">ok</message>'
            '<poke session_id="private_1" target_id="qq_2" /></batch>',
        )
    )

    assert redis_stream.actions == [
        ("private_1", '<message session_id="private_1">ok</message>'),
        ("private_1", '<poke session_id="private_1" target_id="qq_2" />'),
    ]
