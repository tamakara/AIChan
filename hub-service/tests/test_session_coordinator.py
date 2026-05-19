import asyncio

from hub_service.services.session_coordinator import SessionCoordinator
from hub_service.services.stream_models import EventStreamMessage


class StubOutboundClient:
    def __init__(self) -> None:
        self.agent_calls: list[tuple[str, str]] = []
        self.reply_calls: list[tuple[str, str]] = []

    async def call_agent(self, session_id: str, user_message: str) -> str:
        self.agent_calls.append((session_id, user_message))
        await asyncio.sleep(0.05)
        return f"reply:{user_message}"

    async def send_reply(self, session_id: str, content: str) -> None:
        self.reply_calls.append((session_id, content))


def _event(session_id: str, content: str, message_type: str = "private") -> EventStreamMessage:
    return EventStreamMessage(
        event_id=f"ev-{content}",
        session_id=session_id,
        user_id="qq_1",
        content=content,
        source="qq",
        message_type=message_type,  # type: ignore[arg-type]
        raw_event={"x": 1},
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_debounce_merges_messages_for_same_session() -> None:
    outbound = StubOutboundClient()
    coordinator = SessionCoordinator(outbound_client=outbound, debounce_seconds=0.05)

    async def run() -> None:
        await coordinator.submit_event(_event("private_1", "a"))
        await coordinator.submit_event(_event("private_1", "b"))
        await asyncio.sleep(0.2)
        await coordinator.shutdown()

    asyncio.run(run())

    assert outbound.agent_calls == [("private_1", "a\nb")]
    assert outbound.reply_calls == [("private_1", "reply:a\nb")]


def test_running_session_collects_next_round_messages() -> None:
    outbound = StubOutboundClient()
    coordinator = SessionCoordinator(outbound_client=outbound, debounce_seconds=0.01)

    async def run() -> None:
        await coordinator.submit_event(_event("private_1", "first"))
        await asyncio.sleep(0.03)
        await coordinator.submit_event(_event("private_1", "second"))
        await coordinator.submit_event(_event("private_1", "third"))
        await asyncio.sleep(0.3)
        await coordinator.shutdown()

    asyncio.run(run())

    assert outbound.agent_calls[0] == ("private_1", "first")
    assert outbound.agent_calls[1] == ("private_1", "second\nthird")
    assert len(outbound.reply_calls) == 2
