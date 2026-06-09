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


class StubMediaStorage:
    def __init__(self, contents: dict[str, bytes]) -> None:
        self.contents = contents

    async def content(self, object_key: str) -> bytes:
        return self.contents[object_key]


def test_create_session_calls_agent_endpoint() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [
            DummyResponse(
                {
                    "session_id": "agent-1",
                    "metadata": {"platform": "qq", "user_id": 1, "self_id": 10001},
                }
            )
        ]
    )

    agent_session_id = asyncio.run(
        client.create_session("private:1", {"platform": "qq", "user_id": 1, "self_id": 10001})
    )

    assert agent_session_id == "agent-1"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/sessions"
    assert called_payload == {"metadata": {"platform": "qq", "user_id": 1, "self_id": 10001}}


def test_call_session_returns_structured_reply() -> None:
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=StubNapcatWs(),  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"output_xml": "<reply><text>ok!</text></reply>"})]
    )

    reply = asyncio.run(client.call_session("private:1", "agent-1", "<messages />"))

    assert reply is not None
    assert reply.output_xml == "<reply><text>ok!</text></reply>"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/chat"
    assert called_payload == {"session_id": "agent-1", "input_xml": "<messages />"}


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

    asyncio.run(client.send_reply("private:1", "<reply><text>hello!</text></reply>"))

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


def test_send_reply_sends_storage_image_as_base64_segment() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
        media_storage=StubMediaStorage({"qq/private/1/9/1-abc.jpg": b"image-bytes"}),
    )

    asyncio.run(
        client.send_reply(
            "private:1",
            '<reply><text>ok</text><image object_key="qq/private/1/9/1-abc.jpg" /></reply>',
        )
    )

    assert napcat_ws.actions == [
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [
                    {"type": "text", "data": {"text": "ok"}},
                    {"type": "image", "data": {"file": "base64://aW1hZ2UtYnl0ZXM="}},
                ],
                "auto_escape": False,
            },
        )
    ]


def test_send_reply_ignores_empty_reply() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private:1", "<reply />"))

    assert napcat_ws.actions == []
