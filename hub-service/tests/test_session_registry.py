import asyncio

from hub_service.services.session_registry import SessionRegistry
from hub_service.services.stream_models import EventStreamMessage


class StubOutboundClient:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, dict[str, str]]] = []
        self.agent_calls: list[tuple[str, str, list[dict[str, str]]]] = []
        self.reply_calls: list[tuple[str, str]] = []

    async def create_agent(self, session_id: str, metadata: dict[str, str]) -> str:
        self.create_calls.append((session_id, metadata))
        return f"agent-{session_id}"

    async def call_agent(self, session_id: str, agent_id: str, messages) -> str:
        self.agent_calls.append(
            (
                session_id,
                agent_id,
                [message.model_dump() for message in messages],
            )
        )
        await asyncio.sleep(0.05)
        merged = "\n".join(message.content for message in messages)
        return f"reply:{merged}"

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
        raw_event={"time": 1710000000, "x": 1},
        created_at="2026-01-01T00:00:00+00:00",
    )


def test_debounce_merges_messages_for_same_session() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(outbound_client=outbound, debounce_seconds=0.05)
    state: dict[str, int] = {}

    async def run() -> None:
        await registry.submit_event(_event("private_1", "a"))
        await registry.submit_event(_event("private_1", "b"))
        await asyncio.sleep(0.2)
        state["runner_count"] = await registry.active_runner_count()
        await registry.shutdown()

    asyncio.run(run())

    assert outbound.create_calls == [("private_1", {"session_id": "private_1"})]
    assert len(outbound.agent_calls) == 1
    assert outbound.agent_calls[0][0] == "private_1"
    assert outbound.agent_calls[0][1] == "agent-private_1"
    assert [item["content"] for item in outbound.agent_calls[0][2]] == ["a", "b"]
    assert outbound.reply_calls == [("private_1", "reply:a\nb")]
    assert state["runner_count"] == 0


def test_running_session_collects_next_round_messages() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(outbound_client=outbound, debounce_seconds=0.01)
    state: dict[str, int] = {}

    async def run() -> None:
        await registry.submit_event(_event("private_1", "first"))
        await asyncio.sleep(0.03)
        await registry.submit_event(_event("private_1", "second"))
        await registry.submit_event(_event("private_1", "third"))
        await asyncio.sleep(0.3)
        state["runner_count"] = await registry.active_runner_count()
        await registry.shutdown()

    asyncio.run(run())

    assert outbound.create_calls == [("private_1", {"session_id": "private_1"})]
    assert [item["content"] for item in outbound.agent_calls[0][2]] == ["first"]
    assert [item["content"] for item in outbound.agent_calls[1][2]] == ["second", "third"]
    assert outbound.agent_calls[0][1] == outbound.agent_calls[1][1]
    assert len(outbound.reply_calls) == 2
    assert state["runner_count"] == 0


def test_different_sessions_are_dispatched_independently() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(outbound_client=outbound, debounce_seconds=0.01)

    async def run() -> None:
        await registry.submit_event(_event("private_1", "one"))
        await registry.submit_event(_event("private_2", "two"))
        await asyncio.sleep(0.2)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.create_calls) == 2
    assert len(outbound.agent_calls) == 2
    assert {session_id for session_id, *_ in outbound.agent_calls} == {"private_1", "private_2"}
    assert outbound.agent_calls[0][1] != outbound.agent_calls[1][1]
    assert len(outbound.reply_calls) == 2
