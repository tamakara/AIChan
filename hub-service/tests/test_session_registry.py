import asyncio

from hub_service.services.session_registry import SessionRegistry
from hub_service.services.stream_models import EventStreamMessage


class StubOutboundClient:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, dict[str, str]]] = []
        self.agent_calls: list[tuple[str, str, str, list[dict[str, str]]]] = []
        self.agent_call_started_ats: list[float] = []
        self.reply_calls: list[tuple[str, str]] = []
        self.call_delays: list[float] = []

    async def create_agent(self, session_id: str, metadata: dict[str, str]) -> str:
        self.create_calls.append((session_id, metadata))
        return f"agent-{session_id}"

    async def call_agent(self, session_id: str, agent_id: str, messages, message_mode: str) -> str:
        self.agent_call_started_ats.append(asyncio.get_running_loop().time())
        self.agent_calls.append(
            (
                session_id,
                agent_id,
                message_mode,
                [message.model_dump() for message in messages],
            )
        )
        delay = self.call_delays.pop(0) if self.call_delays else 0.05
        await asyncio.sleep(delay)
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
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.05,
    )
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
    assert outbound.agent_calls[0][2] == "start"
    assert [item["content"] for item in outbound.agent_calls[0][3]] == ["a", "b"]
    assert outbound.reply_calls == [("private_1", "reply:a\nb")]
    assert state["runner_count"] == 0


def test_running_session_collects_next_round_messages() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.01,
    )
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
    assert outbound.agent_calls[0][2] == "start"
    assert outbound.agent_calls[1][2] == "append"
    assert [item["content"] for item in outbound.agent_calls[0][3]] == ["first"]
    assert [item["content"] for item in outbound.agent_calls[1][3]] == ["second", "third"]
    assert outbound.agent_calls[0][1] == outbound.agent_calls[1][1]
    assert outbound.reply_calls == [("private_1", "reply:second\nthird")]
    assert state["runner_count"] == 0


def test_different_sessions_are_dispatched_independently() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.01,
    )

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


def test_running_session_discards_stale_reply_and_only_sends_rerun_result() -> None:
    outbound = StubOutboundClient()
    outbound.call_delays = [0.05, 0.05]
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.01,
    )

    async def run() -> None:
        await registry.submit_event(_event("private_1", "first"))
        await asyncio.sleep(0.02)
        await registry.submit_event(_event("private_1", "second"))
        await asyncio.sleep(0.25)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.agent_calls) == 2
    assert outbound.agent_calls[0][2] == "start"
    assert outbound.agent_calls[1][2] == "append"
    assert [item["content"] for item in outbound.agent_calls[0][3]] == ["first"]
    assert [item["content"] for item in outbound.agent_calls[1][3]] == ["second"]
    assert outbound.reply_calls == [("private_1", "reply:second")]


def test_followup_after_reply_starts_next_round() -> None:
    outbound = StubOutboundClient()
    outbound.call_delays = [0.02, 0.02]
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.01,
    )

    async def run() -> None:
        await registry.submit_event(_event("private_1", "first"))
        await asyncio.sleep(0.06)
        await registry.submit_event(_event("private_1", "second"))
        await asyncio.sleep(0.35)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.agent_calls) == 2
    assert outbound.agent_calls[0][2] == "start"
    assert outbound.agent_calls[1][2] == "start"
    assert outbound.reply_calls == [("private_1", "reply:first"), ("private_1", "reply:second")]


def test_rerun_waits_full_debounce_after_run_completion() -> None:
    outbound = StubOutboundClient()
    outbound.call_delays = [0.08, 0.01]
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.05,
    )

    async def run() -> None:
        await registry.submit_event(_event("private_1", "first"))
        # 第二条消息在首轮运行中提前到达；重跑仍应在首轮结束后完整等待一次防抖窗口。
        await asyncio.sleep(0.06)
        await registry.submit_event(_event("private_1", "second"))
        await asyncio.sleep(0.35)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.agent_calls) == 2
    assert outbound.agent_calls[0][2] == "start"
    assert outbound.agent_calls[1][2] == "append"
    assert outbound.agent_call_started_ats[1] - outbound.agent_call_started_ats[0] >= 0.12
    assert outbound.reply_calls == [("private_1", "reply:second")]
