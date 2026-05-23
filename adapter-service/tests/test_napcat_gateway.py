import asyncio

from adapter_service.services.adapter_service import AdapterService
from adapter_service.services.napcat_ws_gateway import NapcatWsGateway


class StubRedisStream:
    def __init__(self) -> None:
        self.events = []

    async def publish_event(self, message) -> None:
        self.events.append(message)


def _private_message_event() -> dict:
    return {
        "time": 1710000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 11,
        "user_id": 20002,
        "message": [{"type": "text", "data": {"text": "hello"}}],
        "raw_message": "hello",
        "font": 14,
        "sender": {"user_id": 20002, "nickname": "alice", "sex": "unknown", "age": 0},
    }


def _private_poke_notice_event() -> dict:
    return {
        "time": 1710000001,
        "self_id": 10001,
        "post_type": "notice",
        "notice_type": "notify",
        "sub_type": "poke",
        "user_id": 20002,
        "target_id": 10001,
    }


def _private_recall_notice_event() -> dict:
    return {
        "time": 1710000002,
        "self_id": 10001,
        "post_type": "notice",
        "notice_type": "friend_recall",
        "user_id": 20002,
        "message_id": 12,
    }


def test_private_event_published_to_stream() -> None:
    redis_stream = StubRedisStream()
    gateway = NapcatWsGateway(
        adapter_service=AdapterService(allowed_message_types={"private"}),
        redis_stream=redis_stream,  # type: ignore[arg-type]
        action_timeout_seconds=3.0,
    )

    asyncio.run(gateway._handle_event(_private_message_event()))  # type: ignore[attr-defined]

    assert len(redis_stream.events) == 1
    message = redis_stream.events[0]
    assert message.session_id == "private_20002"
    assert (
        message.event_xml
        == '<message message_type="private" sub_type="friend" message_id="11" '
        'session_id="private_20002" user_id="qq_20002" time="1710000000">hello</message>'
    )


def test_private_poke_notice_published_to_stream() -> None:
    redis_stream = StubRedisStream()
    gateway = NapcatWsGateway(
        adapter_service=AdapterService(allowed_message_types={"private"}),
        redis_stream=redis_stream,  # type: ignore[arg-type]
        action_timeout_seconds=3.0,
    )

    asyncio.run(gateway._handle_event(_private_poke_notice_event()))  # type: ignore[attr-defined]

    assert len(redis_stream.events) == 1
    message = redis_stream.events[0]
    assert message.session_id == "private_20002"
    assert (
        message.event_xml
        == '<poke session_id="private_20002" user_id="qq_20002" target_id="qq_10001" />'
    )


def test_private_recall_notice_published_to_stream() -> None:
    redis_stream = StubRedisStream()
    gateway = NapcatWsGateway(
        adapter_service=AdapterService(allowed_message_types={"private"}),
        redis_stream=redis_stream,  # type: ignore[arg-type]
        action_timeout_seconds=3.0,
    )

    asyncio.run(gateway._handle_event(_private_recall_notice_event()))  # type: ignore[attr-defined]

    assert len(redis_stream.events) == 1
    message = redis_stream.events[0]
    assert message.session_id == "private_20002"
    assert (
        message.event_xml
        == '<recall session_id="private_20002" user_id="qq_20002" message_id="12" />'
    )

