import asyncio
import json

from hub_service.services.event_consumer import EventConsumerWorker


class StubRedisStream:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def read_pending_events(self, count: int):
        return []

    async def read_new_events(self, count: int):
        return []

    async def ack_event(self, message_id: str) -> None:
        self.acked.append(message_id)


class StubSessionRegistry:
    def __init__(self) -> None:
        self.events = []

    async def submit_event(self, event) -> None:
        self.events.append(event)


def _onebot_message_event(message_type: str, session_id: str, text: str) -> dict:
    return {
        "time": 1710000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": message_type,
        "sub_type": "friend" if message_type == "private" else "normal",
        "message_id": 11,
        "user_id": 1,
        "message": [{"type": "text", "data": {"text": text}}],
        "sender": {"user_id": 1, "nickname": "test"},
    }


def test_private_event_is_forwarded_and_acked() -> None:
    redis_stream = StubRedisStream()
    session_registry = StubSessionRegistry()
    worker = EventConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        session_registry=session_registry,  # type: ignore[arg-type]
    )

    ob_event = _onebot_message_event("private", "private_1", "hello")
    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "private_1",
                        "event": json.dumps(ob_event, ensure_ascii=False),
                        "raw_event": json.dumps(ob_event, ensure_ascii=False),
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert len(session_registry.events) == 1


def test_group_event_is_forwarded_and_acked() -> None:
    redis_stream = StubRedisStream()
    session_registry = StubSessionRegistry()
    worker = EventConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        session_registry=session_registry,  # type: ignore[arg-type]
    )

    ob_event = _onebot_message_event("group", "group_1", "hello")
    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "group_1",
                        "event": json.dumps(ob_event, ensure_ascii=False),
                        "raw_event": json.dumps(ob_event, ensure_ascii=False),
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert len(session_registry.events) == 1


def test_empty_event_is_acked_and_ignored() -> None:
    redis_stream = StubRedisStream()
    session_registry = StubSessionRegistry()
    worker = EventConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        session_registry=session_registry,  # type: ignore[arg-type]
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "private_1",
                        "event": "{}",
                        "raw_event": "{\"time\":1710000000}",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert session_registry.events == []


def test_missing_raw_event_time_is_acked_and_ignored() -> None:
    redis_stream = StubRedisStream()
    session_registry = StubSessionRegistry()
    worker = EventConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        session_registry=session_registry,  # type: ignore[arg-type]
    )

    ob_event = _onebot_message_event("private", "private_1", "hello")
    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "private_1",
                        "event": json.dumps(ob_event, ensure_ascii=False),
                        "raw_event": "{}",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert session_registry.events == []
