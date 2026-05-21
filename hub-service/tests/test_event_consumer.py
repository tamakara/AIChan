import asyncio

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


def test_private_event_is_forwarded_and_acked() -> None:
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
                        "user_id": "qq_1",
                        "content": "hello",
                        "source": "qq",
                        "message_type": "private",
                        "raw_event": "{\"time\":1710000000,\"k\":1}",
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

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "group_1",
                        "user_id": "qq_1",
                        "content": "hello",
                        "source": "qq",
                        "message_type": "group",
                        "raw_event": "{\"time\":1710000000,\"k\":1}",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert len(session_registry.events) == 1


def test_private_empty_content_is_acked_and_ignored() -> None:
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
                        "user_id": "qq_1",
                        "content": "   ",
                        "source": "qq",
                        "message_type": "private",
                        "raw_event": "{\"time\":1710000000,\"k\":1}",
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

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "event_id": "ev1",
                        "session_id": "private_1",
                        "user_id": "qq_1",
                        "content": "hello",
                        "source": "qq",
                        "message_type": "private",
                        "raw_event": "{\"k\":1}",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert session_registry.events == []
