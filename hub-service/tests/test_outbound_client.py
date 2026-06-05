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


class StubNapcatWs:
    def __init__(self) -> None:
        self.actions: list[tuple[str, dict]] = []

    async def send_action(self, action: str, params: dict) -> dict:
        self.actions.append((action, params))
        return {"status": "ok", "retcode": 0}


def test_create_session_calls_agent_endpoint() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"session_id": "agent-1", "metadata": {"session_key": "private:1"}})]
    )

    agent_session_id = asyncio.run(
        client.create_session("private:1", {"session_key": "private:1"})
    )

    assert agent_session_id == "agent-1"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/sessions"
    assert called_payload == {"metadata": {"session_key": "private:1"}}


def test_call_session_returns_structured_reply() -> None:
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=StubNapcatWs(),  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"reply": [{"type": "text", "data": {"text": "ok!"}}], "auto_escape": False})]
    )

    reply = asyncio.run(client.call_session("private:1", "agent-1", "hello"))

    assert reply is not None
    assert reply.content == [{"type": "text", "data": {"text": "ok!"}}]
    assert reply.auto_escape is False
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/chat"
    assert called_payload == {"session_id": "agent-1", "batch": "hello"}


def test_call_session_invalid_response_raises() -> None:
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=StubNapcatWs(),  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient([DummyResponse({"bad": "shape"})])  # type: ignore[attr-defined]

    with pytest.raises(Exception):
        asyncio.run(client.call_session("private:1", "agent-1", "hello"))


def test_send_reply_sends_private_message_action() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private:1", "hello!", auto_escape=False))

    assert napcat_ws.actions == [
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "text", "data": {"text": "hello!"}}],
                "auto_escape": False,
            },
        )
    ]
