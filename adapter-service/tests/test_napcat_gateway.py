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


def test_private_event_published_to_stream() -> None:
    redis_stream = StubRedisStream()
    gateway = NapcatWsGateway(
        adapter_service=AdapterService(),
        redis_stream=redis_stream,  # type: ignore[arg-type]
        action_timeout_seconds=3.0,
    )

    asyncio.run(gateway._handle_event(_private_message_event()))  # type: ignore[attr-defined]

    assert len(redis_stream.events) == 1
    message = redis_stream.events[0]
    assert message.session_id == "private_20002"
    assert message.user_id == "qq_20002"
    assert message.content == "hello"

