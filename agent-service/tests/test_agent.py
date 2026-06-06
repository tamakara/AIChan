import threading
import time

from agent_service.services.agent import Agent
from agent_service.services.session import SessionInterrupted, SessionRegistry
from agent_service.services.observability import NoopObservability
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self) -> None:
        self.model_name = "gpt-test"
        self.calls: list[object] = []

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append((messages, tools_schema, temperature))
        return LlmResponse(content="<reply><text>ok</text></reply>", tool_calls=[], finish_reason="stop")


class FailingLlmClient:
    def __init__(self) -> None:
        self.model_name = "gpt-test"
        self.calls: list[list] = []

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        raise RuntimeError("stub failure")


class BlockingLlmClient:
    """第一次 generate 会阻塞直到 event 被设置，用于测试抢占。"""

    def __init__(self, block_event: threading.Event) -> None:
        self.model_name = "gpt-test"
        self.calls: list[list] = []
        self._block_event = block_event

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        if len(self.calls) == 1:
            self._block_event.wait()
        return LlmResponse(content="<reply><text>ok</text></reply>", tool_calls=[], finish_reason="stop")


class StubMcpGateway:
    def get_tools_schema(self):
        return []

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        return '{"ok": true}'


def _build_agent() -> Agent:
    return Agent(  # type: ignore[arg-type]
        llm_client=StubLlmClient(),
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )


def _build_registry() -> SessionRegistry:
    return SessionRegistry()


def test_create_session_generates_unique_id() -> None:
    registry = _build_registry()
    first = registry.create(metadata={"session_id": "s1"})
    second = registry.create(metadata={"session_id": "s2"})

    assert first.session_id != second.session_id


def test_get_session_hit_and_miss() -> None:
    registry = _build_registry()
    session = registry.create(metadata={})

    assert registry.get(session.session_id) is session
    assert registry.get("missing") is None


def test_session_keeps_metadata_snapshot() -> None:
    registry = _build_registry()
    metadata = {"session_id": "private_1"}
    session = registry.create(metadata=metadata)
    metadata["session_id"] = "mutated"

    assert session.metadata == {"session_id": "private_1"}


def test_delete_session() -> None:
    registry = _build_registry()
    session = registry.create(metadata={})

    assert registry.delete(session.session_id) is True
    assert registry.get(session.session_id) is None
    assert registry.delete("missing") is False


def test_agent_run_session() -> None:
    agent = _build_agent()
    registry = _build_registry()
    session = registry.create(metadata={"session_id": "s1"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == "<reply><text>ok</text></reply>"
    assert [msg["role"] for msg in session._context.messages] == [  # noqa: SLF001
        "system",
        "system",
        "user",
        "assistant",
    ]


def test_session_info_contains_metadata() -> None:
    registry = _build_registry()
    session = registry.create(metadata={"platform": "qq", "user_id": 1, "self_id": 10001})

    assert session._context.messages[1]["content"] == (  # noqa: SLF001
        "<session_info><session_id>"
        f"{session.session_id}"
        "</session_id><platform>qq</platform><user_id>1</user_id>"
        "<self_id>10001</self_id></session_info>"
    )


def test_run_session_interrupted_by_registry_signal() -> None:
    """agent 只响应显式中断信号，抢占触发由 hub-service 负责。"""
    block_event = threading.Event()
    llm_client = BlockingLlmClient(block_event)
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(metadata={"session_id": "s1"})

    result_holder: dict[str, object] = {}

    def first_run() -> None:
        try:
            agent.run(
                session=session,
                user_message="msg_1",
            )
        except SessionInterrupted as exc:
            result_holder["first"] = "interrupted"
            result_holder["interrupted_exc"] = exc
        except Exception as exc:
            result_holder["first"] = f"error: {exc}"

    t = threading.Thread(target=first_run)
    t.start()

    deadline_ts = time.time() + 5.0
    while len(llm_client.calls) < 1 and time.time() < deadline_ts:
        time.sleep(0.01)
    assert len(llm_client.calls) == 1, "first run did not reach LLM call"

    assert registry.interrupt(session.session_id) is True
    block_event.set()
    t.join(timeout=5.0)

    assert result_holder.get("first") == "interrupted", (
        f"expected interrupted, got {result_holder.get('first')}"
    )
    assert len(llm_client.calls) == 1
    assert [msg["role"] for msg in session._context.messages] == [  # noqa: SLF001
        "system",
        "system",
    ]


def test_agent_run_failure_commits_user_and_fallback_reply() -> None:
    llm_client = FailingLlmClient()
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(metadata={"session_id": "s1"})

    reply = agent.run(
        session=session,
        user_message="msg_1",
    )

    assert reply.output_xml == (
        "<reply><text>笨蛋，刚才脑袋短路了一下，稍后再试试喵。</text></reply>"
    )
    assert [msg["role"] for msg in session._context.messages] == [  # noqa: SLF001
        "system",
        "system",
        "user",
        "assistant",
    ]
