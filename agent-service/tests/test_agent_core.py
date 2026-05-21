import json

from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function

from agent_service.services.agent_core import AgentCore
from agent_service.services.types.context import Context
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self._responses = responses
        self.calls: list[tuple[list, list]] = []

    def generate(self, messages, tools_schema, temperature):
        self.calls.append((messages, tools_schema))
        if not self._responses:
            raise RuntimeError("no stub response")
        return self._responses.pop(0)


class StubMcpGateway:
    def __init__(self, tools_schema: list | None = None) -> None:
        self._tools_schema = tools_schema or []
        self.calls: list[tuple[str, dict]] = []

    def get_tools_schema(self):
        return self._tools_schema

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        self.calls.append((tool_name, tool_args))
        if tool_name == "fail_tool":
            raise RuntimeError("tool failed")
        return json.dumps({"ok": True, "tool": tool_name, "args": tool_args}, ensure_ascii=False)


def make_tool_call(tool_id: str, tool_name: str, arguments: str) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        id=tool_id,
        function=Function(name=tool_name, arguments=arguments),
        type="function",
    )


def test_run_returns_llm_stop_response() -> None:
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="final answer", tool_calls=[], finish_reason="stop"),
        ]
    )
    mcp = StubMcpGateway()
    core = AgentCore(llm_client=llm, mcp_gateway=mcp, max_turns=3, temperature=0.0)
    context = Context()

    result = core.run(
        context=context,
    )

    assert result == "final answer"
    assert len(llm.calls) == 1
    assert mcp.calls == []
    assert context.messages[-1]["role"] == "assistant"


def test_run_calls_tool_and_then_completes() -> None:
    tool_call = make_tool_call(tool_id="call_1", tool_name="history", arguments='{"limit": 3}')
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls"),
            LlmResponse(content="done", tool_calls=[], finish_reason="stop"),
        ]
    )
    mcp = StubMcpGateway(
        tools_schema=[
            {"type": "function", "function": {"name": "history", "parameters": {"type": "object"}}}
        ]
    )
    core = AgentCore(llm_client=llm, mcp_gateway=mcp, max_turns=3, temperature=0.0)
    context = Context()

    result = core.run(
        context=context,
    )

    assert result == "done"
    assert len(llm.calls) == 2
    assert mcp.calls == [("history", {"limit": 3})]

    # 工具调用结果必须写回 tool 角色消息，
    # 否则下一轮 LLM 将拿不到工具执行结果，推理链路会断裂。
    tool_messages = [m for m in context.messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call_1"


def test_run_tool_failure_is_captured_into_tool_message() -> None:
    tool_call = make_tool_call(tool_id="call_2", tool_name="fail_tool", arguments='{"x": 1}')
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls"),
            LlmResponse(content="fallback done", tool_calls=[], finish_reason="stop"),
        ]
    )
    mcp = StubMcpGateway()
    core = AgentCore(llm_client=llm, mcp_gateway=mcp, max_turns=3, temperature=0.0)
    context = Context()

    result = core.run(
        context=context,
    )

    assert result == "fallback done"
    tool_messages = [m for m in context.messages if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "tool `fail_tool` failed" in str(tool_messages[0]["content"])


def test_run_raises_when_finish_reason_is_unexpected() -> None:
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="partial", tool_calls=[], finish_reason="length"),
        ]
    )
    core = AgentCore(llm_client=llm, mcp_gateway=StubMcpGateway(), max_turns=2, temperature=0.0)
    context = Context()

    try:
        core.run(
            context=context,
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "unexpected reason" in str(exc)


def test_run_raises_when_exceeding_max_turns() -> None:
    tool_call = make_tool_call(tool_id="call_3", tool_name="history", arguments='{}')
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="", tool_calls=[tool_call], finish_reason="tool_calls"),
        ]
    )
    core = AgentCore(llm_client=llm, mcp_gateway=StubMcpGateway(), max_turns=1, temperature=0.0)
    context = Context()

    try:
        core.run(
            context=context,
        )
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "within 1 turns" in str(exc)
