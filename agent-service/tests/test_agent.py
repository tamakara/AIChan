from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function

from agent_service.services.agent import Agent
from agent_service.services.observability import NoopObservability
from agent_service.services.session import SessionRegistry
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self) -> None:
        self.model_name = "gpt-test"
        self.calls: list[object] = []

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append((messages, tools_schema, temperature))
        return LlmResponse(content="<reply><text>ok</text></reply>", tool_calls=[], finish_reason="stop")


class SequencedLlmClient:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self.model_name = "gpt-test"
        self.calls: list[list] = []
        self._responses = responses

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        if not self._responses:
            raise RuntimeError("no response")
        return self._responses.pop(0)


class FailingLlmClient:
    def __init__(self) -> None:
        self.model_name = "gpt-test"
        self.calls: list[list] = []

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        raise RuntimeError("stub failure")


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
    return SessionRegistry(max_turns=3)


def _tool_call(tool_name: str) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        id="call_1",
        function=Function(name=tool_name, arguments='{"x": 1}'),
        type="function",
    )


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
        "system",
        "user",
        "assistant",
    ]


def test_session_info_contains_metadata() -> None:
    registry = _build_registry()
    session = registry.create(metadata={"platform": "qq", "user_id": 1, "self_id": 10001})

    assert session._context.messages[1]["content"] == (  # noqa: SLF001
        f'<session_info session_id="{session.session_id}" max_turn="3" '
        'platform="qq" user_id="1" self_id="10001" />'
    )


def test_stop_with_queued_message_drops_final_reply_and_continues() -> None:
    llm_client = SequencedLlmClient(
        [
            LlmResponse(content="<reply><text>old</text></reply>", tool_calls=[], finish_reason="stop"),
            LlmResponse(content="<reply><text>new</text></reply>", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(metadata={"session_id": "s1"})
    session.queue_user_message("<batch><message><text>queued</text></message></batch>")

    reply = agent.run(
        session=session,
        user_message="<batch><message><text>first</text></message></batch>",
    )

    assert reply.output_xml == "<reply><text>new</text></reply>"
    assert len(llm_client.calls) == 2
    second_call_contents = [str(msg["content"]) for msg in llm_client.calls[1]]
    assert "<reply><text>old</text></reply>" not in second_call_contents
    assert "<batch><message><text>queued</text></message></batch>" in second_call_contents
    persisted_contents = [str(msg["content"]) for msg in session._context.messages]  # noqa: SLF001
    assert "<reply><text>old</text></reply>" not in persisted_contents
    assert "<reply><text>new</text></reply>" in persisted_contents


def test_tool_call_turn_inserts_queued_message_after_tool_result() -> None:
    llm_client = SequencedLlmClient(
        [
            LlmResponse(content="", tool_calls=[_tool_call("history")], finish_reason="tool_calls"),
            LlmResponse(content="<reply><text>done</text></reply>", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(metadata={"session_id": "s1"})
    session.queue_user_message("<batch><message><text>queued</text></message></batch>")

    reply = agent.run(
        session=session,
        user_message="<batch><message><text>first</text></message></batch>",
    )

    assert reply.output_xml == "<reply><text>done</text></reply>"
    second_call_roles = [msg["role"] for msg in llm_client.calls[1]]
    second_call_contents = [str(msg["content"]) for msg in llm_client.calls[1]]
    assert second_call_roles == [
        "system",
        "system",
        "system",
        "user",
        "assistant",
        "tool",
        "system",
        "user",
    ]
    assert second_call_contents[-3] == '{"ok": true}'
    assert second_call_contents[-2] == '<turn index="2" />'
    assert second_call_contents[-1] == "<batch><message><text>queued</text></message></batch>"


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
        "system",
        "user",
        "assistant",
    ]
