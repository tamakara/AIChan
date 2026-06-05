import asyncio

from hub_service.services.outbound_client import AgentReply
from hub_service.services.session_registry import SessionRegistry


class StubOutboundClient:
    def __init__(self) -> None:
        self.create_calls: list[tuple[str, dict[str, str]]] = []
        self.session_calls: list[tuple[str, str, str]] = []
        self.session_call_started_ats: list[float] = []
        self.replies: list[tuple[str, str | list[dict], bool]] = []
        self.call_delays: list[float] = []

    async def create_session(self, hub_session_key: str, metadata: dict[str, str]) -> str:
        self.create_calls.append((hub_session_key, metadata))
        return f"agent-{hub_session_key}"

    async def interrupt_session(self, agent_session_id: str) -> None:
        return

    async def call_session(
        self, hub_session_key: str, agent_session_id: str, text: str
    ) -> AgentReply | None:
        self.session_call_started_ats.append(asyncio.get_running_loop().time())
        self.session_calls.append((hub_session_key, agent_session_id, text))
        delay = self.call_delays.pop(0) if self.call_delays else 0.05
        await asyncio.sleep(delay)
        return AgentReply(content=f"reply:{text}", auto_escape=False)

    async def send_reply(
        self,
        session_key: str,
        content: str | list[dict],
        auto_escape: bool,
    ) -> None:
        self.replies.append((session_key, content, auto_escape))


def _event(user_id: int, content: str) -> dict:
    return {
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": content,
        "user_id": user_id,
        "self_id": 10001,
        "time": 1710000000,
        "message": [{"type": "text", "data": {"text": content}}],
    }


def test_debounce_merges_messages_for_same_session() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(
        outbound_client=outbound,  # type: ignore[arg-type]
        debounce_seconds=0.05,
    )
    state: dict[str, int] = {}

    async def run() -> None:
        await registry.submit_event(_event(1, "a"))
        await registry.submit_event(_event(1, "b"))
        await asyncio.sleep(0.2)
        state["runner_count"] = await registry.active_runner_count()
        await registry.shutdown()

    asyncio.run(run())

    assert outbound.create_calls == [("private:1", {"session_key": "private:1"})]
    assert len(outbound.session_calls) == 1
    assert outbound.session_calls[0][0] == "private:1"
    assert outbound.session_calls[0][1] == "agent-private:1"
    assert '"message_id": "a"' in outbound.session_calls[0][2]
    assert '"message_id": "b"' in outbound.session_calls[0][2]
    assert outbound.replies[0][0] == "private:1"
    assert state["runner_count"] == 0


def test_running_session_triggers_followup_batch() -> None:
    outbound = StubOutboundClient()
    outbound.call_delays = [0.08, 0.02]
    registry = SessionRegistry(
        outbound_client=outbound,  # type: ignore[arg-type]
        debounce_seconds=0.01,
    )

    async def run() -> None:
        await registry.submit_event(_event(1, "first"))
        await asyncio.sleep(0.03)
        await registry.submit_event(_event(1, "second"))
        await registry.submit_event(_event(1, "third"))
        await asyncio.sleep(0.3)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.session_calls) == 2
    assert '"message_id": "first"' in outbound.session_calls[0][2]
    assert '"message_id": "second"' in outbound.session_calls[1][2]
    assert '"message_id": "third"' in outbound.session_calls[1][2]
    assert len(outbound.replies) == 2


def test_different_sessions_are_dispatched_independently() -> None:
    outbound = StubOutboundClient()
    registry = SessionRegistry(
        outbound_client=outbound,  # type: ignore[arg-type]
        debounce_seconds=0.01,
    )

    async def run() -> None:
        await registry.submit_event(_event(1, "one"))
        await registry.submit_event(_event(2, "two"))
        await asyncio.sleep(0.2)
        await registry.shutdown()

    asyncio.run(run())

    assert len(outbound.create_calls) == 2
    assert len(outbound.session_calls) == 2
    assert {session_key for session_key, *_ in outbound.session_calls} == {"private:1", "private:2"}
    assert outbound.session_calls[0][1] != outbound.session_calls[1][1]
