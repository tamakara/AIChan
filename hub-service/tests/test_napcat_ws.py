import asyncio

from hub_service.services.connection_state import NapcatConnectionState
from hub_service.services.napcat_ws import NapcatWsGateway


def _event(user_id: int = 1, message_type: str = "private", post_type: str = "message") -> dict:
    return {
        "post_type": post_type,
        "message_type": message_type,
        "user_id": user_id,
        "self_id": 10001,
        "time": 1710000000,
        "message_id": 9,
        "message": [{"type": "text", "data": {"text": "hello"}}],
    }


def test_empty_whitelist_ignores_private_message() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        allowed_user_ids=set(),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event()))  # noqa: SLF001

    assert seen == []


def test_whitelist_allows_private_message() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        allowed_user_ids={1},
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event()))  # noqa: SLF001

    assert len(seen) == 1


def test_group_and_non_message_events_are_ignored() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        allowed_user_ids={1},
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event(message_type="group")))  # noqa: SLF001
    asyncio.run(gateway._handle_event(_event(post_type="notice")))  # noqa: SLF001

    assert seen == []


async def _record(target: list[dict], event: dict) -> None:
    target.append(event)
