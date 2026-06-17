import re

from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function

from agent_service.services.agent import Agent
from agent_service.services.memory_client import MemoryCompressResult
from agent_service.services.observability import NoopObservability, RunTrace
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


class StubMemoryClient:
    def __init__(
        self,
        reads: list[str] | None = None,
        compress_result: MemoryCompressResult | None = None,
        fail_read: bool = False,
        fail_compress: bool = False,
    ) -> None:
        self.reads = reads or [""]
        self.compress_result = compress_result or MemoryCompressResult(
            content_markdown="- 已压缩记忆\n",
            added_markdown="- 已压缩记忆",
            added_count=1,
        )
        self.fail_read = fail_read
        self.fail_compress = fail_compress
        self.read_calls: list[str] = []
        self.compress_calls: list[tuple[str, str]] = []

    def read(self, session_id: str) -> str:
        self.read_calls.append(session_id)
        if self.fail_read:
            raise RuntimeError("read failed")
        if len(self.reads) > 1:
            return self.reads.pop(0)
        return self.reads[0]

    def compress(self, session_id: str, messages_text: str) -> MemoryCompressResult:
        self.compress_calls.append((session_id, messages_text))
        if self.fail_compress:
            raise RuntimeError("compress failed")
        return self.compress_result


class RecordingObservability:
    def __init__(self) -> None:
        self.llm_inputs: list[list[object]] = []

    def start_run(
        self,
        *,
        session_id: str,
        message_count: int,
        max_turns: int,
        agent_metadata: dict[str, object],
    ) -> RunTrace:
        return RunTrace(run_id="run_1", trace_name="agent.chat.run")

    def llm_generation(
        self,
        *,
        run: RunTrace,
        turn: int,
        input_messages: list[object],
        output_content: str,
        output_tool_calls: list[object],
        finish_reason: str,
        model: str,
        duration_ms: int,
    ) -> None:
        self.llm_inputs.append(list(input_messages))

    def tool_span(
        self,
        *,
        run: RunTrace,
        turn: int,
        tool_name: str,
        tool_args: dict[str, object],
        status: str,
        error: str | None,
        duration_ms: int,
        output: str | None,
    ) -> None:
        return

    def finish_run_success(
        self,
        *,
        run: RunTrace,
        output: object,
        duration_ms: int,
    ) -> None:
        return

    def finish_run_error(
        self,
        *,
        run: RunTrace,
        error: str,
        duration_ms: int,
    ) -> None:
        return

    def flush(self, timeout_seconds: float) -> None:
        return


def _build_agent() -> Agent:
    return Agent(  # type: ignore[arg-type]
        llm_client=StubLlmClient(),
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )


def _build_agent_with_memory(
    *,
    llm_client=None,
    memory_client: StubMemoryClient | None = None,
    compress_every: int = 10,
) -> Agent:
    return Agent(  # type: ignore[arg-type]
        llm_client=llm_client or StubLlmClient(),
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
        memory_client=memory_client or StubMemoryClient(),
        memory_enabled=True,
        memory_compress_every_n_records=compress_every,
    )


def _build_registry() -> SessionRegistry:
    return SessionRegistry(max_turns=3)


def _tool_call(tool_name: str) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        id="call_1",
        function=Function(name=tool_name, arguments='{"x": 1}'),
        type="function",
    )


def test_create_session_uses_provided_session_id() -> None:
    registry = _build_registry()
    first = registry.create(session_id="private_1", metadata={"session_type": "private"})
    second = registry.create(session_id="group_2", metadata={"session_type": "group"})

    assert first.session_id == "private_1"
    assert second.session_id == "group_2"


def test_get_session_hit_and_miss() -> None:
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={})

    assert registry.get(session.session_id) is session
    assert registry.get("missing") is None


def test_session_keeps_metadata_snapshot() -> None:
    registry = _build_registry()
    metadata = {"session_type": "private"}
    session = registry.create(session_id="private_1", metadata=metadata)
    metadata["session_id"] = "mutated"

    assert session.metadata == {"session_type": "private", "session_id": "private_1"}


def test_delete_session() -> None:
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={})

    assert registry.delete(session.session_id) is True
    assert registry.get(session.session_id) is None
    assert registry.delete("missing") is False


def test_agent_run_session() -> None:
    agent = _build_agent()
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == "<reply><text>ok</text></reply>"
    assert [msg["role"] for msg in session.messages] == [
        "system",
        "system",
        "system",
        "user",
        "assistant",
    ]


def test_agent_run_commits_normalized_reply_when_llm_returns_broken_xml() -> None:
    llm_client = SequencedLlmClient(
        [
            LlmResponse(content="<reply><text>broken", tool_calls=[], finish_reason="stop"),
            LlmResponse(content="<reply><text>fixed</text></reply>", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == "<reply><text>fixed</text></reply>"
    assert session.messages[-1]["content"] == reply.output_xml
    assert len(llm_client.calls) == 2


def test_agent_run_returns_fallback_when_invalid_xml_retries_exhausted() -> None:
    llm_client = SequencedLlmClient(
        [
            LlmResponse(content="<reply><text>broken", tool_calls=[], finish_reason="stop"),
            LlmResponse(content="<reply><text>still broken", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == (
        "<reply><text>笨蛋，刚才脑袋短路了一下，稍后再试试喵。</text></reply>"
    )
    assert session.messages[-1]["content"] == reply.output_xml


def test_session_system_message_contains_metadata() -> None:
    registry = _build_registry()
    session = registry.create(
        session_id="group_20001",
        metadata={"platform": "qq", "session_type": "group", "group_id": 20001, "self_id": 10001},
    )

    assert session.messages[1]["content"] == (
        '<session session_id="group_20001" max_turn="3" '
        'platform="qq" session_type="group" group_id="20001" self_id="10001" />'
    )


def test_session_record_messages_text_uses_timestamped_log_format() -> None:
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    session.append_record_messages_locked(
        [
            {"role": "system", "content": '<turn index="1" />'},
            {"role": "user", "content": "first line\nsecond line"},
            {"role": "assistant", "content": "<reply><text>ok</text></reply>"},
            {"role": "tool", "content": '{"ok": true}', "tool_call_id": "call_1"},
        ]
    )

    messages_text = session.record_messages_text_locked()

    assert '<turn index="1" />' not in messages_text
    assert re.search(r"^\[[^\]]+\] user: first line$", messages_text, re.MULTILINE)
    assert re.search(r"^\[[^\]]+\] user: second line$", messages_text, re.MULTILINE)
    assert re.search(r"^\[[^\]]+\] assistant: <reply><text>ok</text></reply>$", messages_text, re.MULTILINE)
    assert re.search(r'^\[[^\]]+\] tool\[call_1\]: \{"ok": true\}$', messages_text, re.MULTILINE)


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
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})
    session.queue_user_message("<messages><message><text>queued</text></message></messages>")

    reply = agent.run(
        session=session,
        user_message="<messages><message><text>first</text></message></messages>",
    )

    assert reply.output_xml == "<reply><text>new</text></reply>"
    assert len(llm_client.calls) == 2
    second_call_contents = [str(msg["content"]) for msg in llm_client.calls[1]]
    assert "<reply><text>old</text></reply>" not in second_call_contents
    assert "<messages><message><text>queued</text></message></messages>" in second_call_contents
    persisted_contents = [str(msg["content"]) for msg in session.messages]
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
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})
    session.queue_user_message("<messages><message><text>queued</text></message></messages>")

    reply = agent.run(
        session=session,
        user_message="<messages><message><text>first</text></message></messages>",
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
    assert second_call_contents[-1] == "<messages><message><text>queued</text></message></messages>"


def test_agent_run_failure_commits_user_and_fallback_reply() -> None:
    llm_client = FailingLlmClient()
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=NoopObservability(),
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="msg_1",
    )

    assert reply.output_xml == (
        "<reply><text>笨蛋，刚才脑袋短路了一下，稍后再试试喵。</text></reply>"
    )
    assert [msg["role"] for msg in session.messages] == [
        "system",
        "system",
        "system",
        "user",
        "assistant",
    ]


def test_agent_run_injects_memory_before_record_messages() -> None:
    memory_client = StubMemoryClient(reads=["- 用户喜欢直接结论\n"])
    llm_client = StubLlmClient()
    agent = _build_agent_with_memory(llm_client=llm_client, memory_client=memory_client)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")

    called_messages = llm_client.calls[0][0]
    assert memory_client.read_calls == ["private_1"]
    assert [msg["role"] for msg in called_messages[:4]] == ["system", "system", "system", "system"]
    assert "以下是该会话的长期记忆" in str(called_messages[2]["content"])
    assert "- 用户喜欢直接结论" in str(called_messages[2]["content"])
    assert called_messages[3]["content"] == '<turn index="1" />'


def test_agent_run_injects_empty_memory_placeholder() -> None:
    memory_client = StubMemoryClient(reads=[""])
    llm_client = StubLlmClient()
    agent = _build_agent_with_memory(llm_client=llm_client, memory_client=memory_client)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")

    called_messages = llm_client.calls[0][0]
    assert "暂无可用长期记忆。" in str(called_messages[2]["content"])


def test_agent_run_skips_memory_when_read_fails() -> None:
    memory_client = StubMemoryClient(fail_read=True)
    llm_client = StubLlmClient()
    agent = _build_agent_with_memory(llm_client=llm_client, memory_client=memory_client)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(session=session, user_message="hello")

    assert reply.output_xml == "<reply><text>ok</text></reply>"
    called_messages = llm_client.calls[0][0]
    assert called_messages[2]["content"] == '<turn index="1" />'


def test_agent_compresses_and_trims_records_after_threshold() -> None:
    memory_client = StubMemoryClient(
        reads=["- 旧记忆\n"],
        compress_result=MemoryCompressResult(
            content_markdown="- 旧记忆\n- 新记忆\n",
            added_markdown="- 新记忆",
            added_count=1,
        ),
    )
    agent = _build_agent_with_memory(memory_client=memory_client, compress_every=1)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")

    assert len(memory_client.compress_calls) == 1
    _, messages_text = memory_client.compress_calls[0]
    assert re.search(r"^\[[^\]]+\] user: hello$", messages_text, re.MULTILINE)
    assert re.search(
        r"^\[[^\]]+\] assistant: <reply><text>ok</text></reply>$",
        messages_text,
        re.MULTILINE,
    )
    assert "<turn " not in messages_text
    assert "<session " not in messages_text
    assert "以下是该会话的长期记忆" not in messages_text
    assert [msg["role"] for msg in session.messages] == ["system", "system", "system"]
    memory_message = session.memory_message_locked()
    assert memory_message is not None
    assert "- 新记忆" in str(memory_message["content"])


def test_agent_compresses_when_record_count_reaches_threshold() -> None:
    memory_client = StubMemoryClient(
        reads=["- 旧记忆\n"],
        compress_result=MemoryCompressResult(
            content_markdown="- 旧记忆\n- 新记忆\n",
            added_markdown="- 新记忆",
            added_count=1,
        ),
    )
    agent = _build_agent_with_memory(memory_client=memory_client, compress_every=3)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")

    assert len(memory_client.compress_calls) == 1
    assert session.record_message_count_locked() == 0


def test_next_run_after_compress_only_contains_system_memory_and_new_input() -> None:
    memory_client = StubMemoryClient(
        reads=["- 旧记忆\n", "- 旧记忆\n- 新记忆\n"],
        compress_result=MemoryCompressResult(
            content_markdown="- 旧记忆\n- 新记忆\n",
            added_markdown="- 新记忆",
            added_count=1,
        ),
    )
    llm_client = StubLlmClient()
    agent = _build_agent_with_memory(
        llm_client=llm_client,
        memory_client=memory_client,
        compress_every=3,
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")
    agent.run(session=session, user_message="again")

    second_call_messages = llm_client.calls[1][0]
    second_call_contents = [str(msg["content"]) for msg in second_call_messages]
    second_call_roles = [msg["role"] for msg in second_call_messages]

    assert second_call_roles == ["system", "system", "system", "system", "user"]
    assert "hello" not in second_call_contents[-1]
    assert "<reply><text>ok</text></reply>" not in second_call_contents
    assert "- 新记忆" in str(second_call_messages[2]["content"])
    assert second_call_contents[3] == '<turn index="1" />'
    assert second_call_contents[4] == "again"


def test_agent_keeps_records_when_compress_fails_and_waits_next_cycle() -> None:
    memory_client = StubMemoryClient(reads=[""], fail_compress=True)
    agent = _build_agent_with_memory(memory_client=memory_client, compress_every=3)
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="first")
    after_failure_len = len(session.messages)
    agent.run(session=session, user_message="second")

    assert len(memory_client.compress_calls) == 2
    assert len(session.messages) > 3
    assert len(session.messages) > after_failure_len


def test_langfuse_input_messages_match_actual_llm_input_after_compress() -> None:
    memory_client = StubMemoryClient(
        reads=["- 旧记忆\n", "- 旧记忆\n- 新记忆\n"],
        compress_result=MemoryCompressResult(
            content_markdown="- 旧记忆\n- 新记忆\n",
            added_markdown="- 新记忆",
            added_count=1,
        ),
    )
    llm_client = StubLlmClient()
    observability = RecordingObservability()
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=observability,
        memory_client=memory_client,
        memory_enabled=True,
        memory_compress_every_n_records=3,
    )
    registry = _build_registry()
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    agent.run(session=session, user_message="hello")
    agent.run(session=session, user_message="again")

    llm_second_call = llm_client.calls[1][0]
    observed_second_call = observability.llm_inputs[1]

    assert observed_second_call == llm_second_call
    assert [msg["role"] for msg in observed_second_call] == [
        "system",
        "system",
        "system",
        "system",
        "user",
    ]





