import asyncio

import pytest

from hub_service.services.media_storage import StoredMedia
from hub_service.services.outbound_client import OutboundClient

IMAGE_KEY = "a" * 64
FILE_KEY = "b" * 64


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
    def __init__(self, contents: dict[str, bytes], metadata: dict[str, StoredMedia] | None = None) -> None:
        self.contents = contents
        self.metadata_items = metadata or {}

    async def metadata(self, object_key: str) -> StoredMedia:
        return self.metadata_items.get(
            object_key,
            StoredMedia(
                object_key=object_key,
                name=object_key.rsplit("/", 1)[-1],
                mime="application/octet-stream",
                size=len(self.contents[object_key]),
                sha256="",
            ),
        )

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
        client.create_session(
            "private_1",
            {"platform": "qq", "session_id": "private_1", "session_type": "private", "user_id": 1, "self_id": 10001},
        )
    )

    assert agent_session_id == "agent-1"
    called_url, called_payload = client._client.calls[0]  # type: ignore[attr-defined]
    assert called_url == "http://agent-service:8000/sessions"
    assert called_payload == {
        "session_id": "private_1",
        "metadata": {
            "platform": "qq",
            "session_id": "private_1",
            "session_type": "private",
            "user_id": 1,
            "self_id": 10001,
        },
    }


def test_call_session_returns_structured_reply() -> None:
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=StubNapcatWs(),  # type: ignore[arg-type]
    )
    client._client = DummyHttpClient(  # type: ignore[attr-defined]
        [DummyResponse({"output_xml": "<reply><text>ok!</text></reply>"})]
    )

    reply = asyncio.run(client.call_session("private_1", "agent-1", "<messages />"))

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
        asyncio.run(client.call_session("private_1", "agent-1", "hello"))


def test_send_reply_sends_private_message_action() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private_1", "<reply><text>hello!</text></reply>"))

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
        media_storage=StubMediaStorage({IMAGE_KEY: b"image-bytes"}),
    )

    asyncio.run(
        client.send_reply(
            "private_1",
            f'<reply><text>ok</text><image object_key="{IMAGE_KEY}" /></reply>',
        )
    )

    assert napcat_ws.actions == [
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "text", "data": {"text": "ok"}}],
                "auto_escape": False,
            },
        ),
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "image", "data": {"file": "base64://aW1hZ2UtYnl0ZXM="}}],
                "auto_escape": False,
            },
        )
    ]


def test_send_reply_uploads_storage_file() -> None:
    napcat_ws = StubNapcatWs()
    object_key = FILE_KEY
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
        media_storage=StubMediaStorage(
            {object_key: b"hello"},
            {
                object_key: StoredMedia(
                    object_key=object_key,
                    name="note.txt",
                    mime="text/plain",
                    size=5,
                    sha256=object_key,
                )
            },
        ),
    )

    asyncio.run(
        client.send_reply(
            "private_1",
            f'<reply><text>see file</text><file object_key="{object_key}" /></reply>',
        )
    )

    assert napcat_ws.actions == [
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "text", "data": {"text": "see file"}}],
                "auto_escape": False,
            },
        ),
        (
            "upload_private_file",
            {"user_id": 1, "file": "base64://aGVsbG8=", "name": "note.txt"},
        ),
    ]


def test_send_reply_splits_repeated_text_nodes() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private_1", "<reply><text>one</text><text>two</text></reply>"))

    assert napcat_ws.actions == [
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "text", "data": {"text": "one"}}],
                "auto_escape": False,
            },
        ),
        (
            "send_private_msg",
            {
                "user_id": 1,
                "message": [{"type": "text", "data": {"text": "two"}}],
                "auto_escape": False,
            },
        ),
    ]


def test_send_reply_ignores_empty_reply() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(client.send_reply("private_1", "<reply />"))

    assert napcat_ws.actions == []


def test_send_reply_sends_group_message_with_at_target() -> None:
    napcat_ws = StubNapcatWs()
    client = OutboundClient(
        agent_service_url="http://agent-service:8000",
        napcat_ws=napcat_ws,  # type: ignore[arg-type]
    )

    asyncio.run(
        client.send_reply(
            "group_20001",
            '<reply><message target_user_id="2" target_nickname="小红" at="true">'
            "<text>收到喵</text></message></reply>",
        )
    )

    assert napcat_ws.actions == [
        (
            "send_group_msg",
            {
                "group_id": 20001,
                "message": [
                    {"type": "at", "data": {"qq": "2"}},
                    {"type": "text", "data": {"text": " "}},
                    {"type": "text", "data": {"text": "收到喵"}},
                ],
                "auto_escape": False,
            },
        )
    ]
