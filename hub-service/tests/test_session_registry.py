import asyncio

from hub_service.services.session_registry import SessionRegistry
from hub_service.services.stream_models import EventStreamMessage


class StubOutboundClient:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, dict[str, str]]] = []
        self.session_calls: list[tuple[str, str, str]] = []
        self.session_call_started_ats: list[float] = []
        self.replies: list[tuple[str, str]] = []
        self.call_delays: list[float] = []

    async def create_session(self, hub_session_id: str, metadata: dict[str, str]) -> str:
        self.create_calls.append((hub_session_id, metadata))
        return f"agent-{hub_session_id}"

    async def call_session(
        self, hub_session_id: str, agent_session_id: str, text: str
    ) -> str:
        self.session_call_started_ats.append(asyncio.get_running_loop().time())
        self.session_calls.append((hub_session_id, agent_session_id, text))
        delay = self.call_delays.pop(0) if self.call_delays else 0.05
        await asyncio.sleep(delay)
        return f"reply:{text}"

    async def send_reply(self, session_id: str, content: str) -> None:
        self.replies.append((session_id, content))


def _event(session_id: str, content: str) -> EventStreamMessage:
    return EventStreamMessage(
        event_id=f"ev-{content}",
        session_id=session_id,
        event={
            "post_type": "message",
            "message_type": "private",
            "sub_type": "friend",
            "message_id": content,
            "user_id": 1,
            "self_id": 10001,
            "time": 1710000000,
            "message": [{"type": "text", "data": {"text": content}}],
        },
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
    assert len(outbound.session_calls) == 1
    assert outbound.session_calls[0][0] == "private_1"
    assert outbound.session_calls[0][1] == "agent-private_1"
    # 两条消息的文本被合并发送。
    assert "a" in outbound.session_calls[0][2]
    assert "b" in outbound.session_calls[0][2]
    assert outbound.replies == [("private_1", "reply:a\nb")]
    assert state["runner_count"] == 0


def test_running_session_triggers_immediate_followup() -> None:
    """运行期间到达的新消息应立即触发新请求以抢占 agent 侧的旧生成。"""
    outbound = StubOutboundClient()
    outbound.call_delays = [0.08, 0.02]
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
    assert len(outbound.session_calls) == 2
    assert "first" in outbound.session_calls[0][2]
    assert "second" in outbound.session_calls[1][2]
    assert "third" in outbound.session_calls[1][2]
    assert len(outbound.replies) == 2
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
    assert len(outbound.session_calls) == 2
    assert {sid for sid, *_ in outbound.session_calls} == {"private_1", "private_2"}
    assert outbound.session_calls[0][1] != outbound.session_calls[1][1]
    assert len(outbound.replies) == 2


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

    assert len(outbound.session_calls) == 2
    assert outbound.replies == [
        ("private_1", "reply:first"),
        ("private_1", "reply:second"),
    ]


def test_mid_run_events_fire_after_debounce() -> None:
    """运行期间到达的消息在防抖窗口后触发新请求。"""
    outbound = StubOutboundClient()
    outbound.call_delays = [0.08, 0.01]
    registry = SessionRegistry(
        outbound_client=outbound,
        debounce_seconds=0.05,
    )

    async def run() -> None:
        await registry.submit_event(_event("private_1", "first"))
        deadline = asyncio.get_running_loop().time() + 0.5
        while not outbound.session_call_started_ats:
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("first run did not start in expected time")
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)
        await registry.submit_event(_event("private_1", "second"))
        await asyncio.sleep(0.35)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.session_calls) == 2
    assert outbound.session_call_started_ats[1] - outbound.session_call_started_ats[0] >= 0.04
    assert len(outbound.replies) == 2
