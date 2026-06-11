import asyncio

from hub_service.services.connection_state import NapcatConnectionState
from hub_service.services.napcat_ws import NapcatWsGateway, SessionAccessRule


def _rule(
    session_id: str,
    *,
    require_mention: bool = False,
    blocked_user_ids: frozenset[int] = frozenset(),
) -> SessionAccessRule:
    return SessionAccessRule(
        session_id=session_id,
        enabled=True,
        require_mention=require_mention,
        blocked_user_ids=blocked_user_ids,
    )


def _event(user_id: int = 1, message_type: str = "private", post_type: str = "message", at_bot: bool = False) -> dict:
    event = {
        "post_type": post_type,
        "message_type": message_type,
        "user_id": user_id,
        "self_id": 10001,
        "time": 1710000000,
        "message_id": 9,
        "message": [{"type": "text", "data": {"text": "hello"}}],
    }
    if message_type == "group":
        event["group_id"] = 20001
    if at_bot:
        event["message"].insert(0, {"type": "at", "data": {"qq": "10001"}})
    return event


def test_empty_whitelist_ignores_private_message() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        session_whitelist=(),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event()))  # noqa: SLF001

    assert seen == []


def test_whitelist_allows_private_message() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        session_whitelist=(_rule("private_1"),),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event()))  # noqa: SLF001

    assert len(seen) == 1


def test_group_requires_mention_when_configured() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        session_whitelist=(_rule("group_20001", require_mention=True),),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event(message_type="group")))  # noqa: SLF001
    asyncio.run(gateway._handle_event(_event(message_type="group", at_bot=True)))  # noqa: SLF001

    assert len(seen) == 1


def test_blocked_group_user_is_ignored_even_when_mentioned() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        session_whitelist=(_rule("group_20001", require_mention=True, blocked_user_ids=frozenset({1})),),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event(message_type="group", at_bot=True)))  # noqa: SLF001

    assert seen == []


def test_non_message_events_are_ignored() -> None:
    seen: list[dict] = []
    gateway = NapcatWsGateway(
        connection_state=NapcatConnectionState(),
        action_timeout_seconds=1,
        session_whitelist=(_rule("private_1"),),
        on_event=lambda event: _record(seen, event),
    )

    asyncio.run(gateway._handle_event(_event(post_type="notice")))  # noqa: SLF001

    assert seen == []


async def _record(target: list[dict], event: dict) -> None:
    target.append(event)
