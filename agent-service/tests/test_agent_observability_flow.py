import json

from openai.types.chat import ChatCompletionMessageFunctionToolCall
from openai.types.chat.chat_completion_message_function_tool_call import Function

from agent_service.services.agent import Agent
from agent_service.services.session import SessionRegistry
from agent_service.services.observability import RunTrace
from agent_service.services.types.llm import LlmResponse


class SpyObservability:
    def __init__(self) -> None:
        self.started: list[dict] = []
        self.generations: list[dict] = []
        self.tools: list[dict] = []
        self.success: list[dict] = []
        self.errors: list[dict] = []

    def start_run(self, *, session_id: str, message_count: int, max_turns: int, agent_metadata: dict):
        payload = {
            "session_id": session_id,
            "message_count": message_count,
            "max_turns": max_turns,
            "agent_metadata": agent_metadata,
        }
        self.started.append(payload)
        return RunTrace(run_id="run_1", trace_name="agent.chat.run")

    def llm_generation(self, **kwargs) -> None:
        self.generations.append(kwargs)

    def tool_span(self, **kwargs) -> None:
        self.tools.append(kwargs)

    def finish_run_success(self, **kwargs) -> None:
        self.success.append(kwargs)

    def finish_run_error(self, **kwargs) -> None:
        self.errors.append(kwargs)

    def flush(self, timeout_seconds: float) -> None:
        return


class StubLlmClient:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self._responses = responses
        self.model_name = "gpt-test"

    def generate(self, messages, tools_schema, temperature):
        if not self._responses:
            raise RuntimeError("no stub response")
        return self._responses.pop(0)


class StubMcpGateway:
    def get_tools_schema(self):
        return []

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        if tool_name == "fail_tool":
            raise RuntimeError("tool failed")
        return json.dumps({"ok": True}, ensure_ascii=False)


def _tool_call(tool_name: str) -> ChatCompletionMessageFunctionToolCall:
    return ChatCompletionMessageFunctionToolCall(
        id="call_1",
        function=Function(name=tool_name, arguments='{"x": 1}'),
        type="function",
    )


def test_agent_reports_full_observability_flow() -> None:
    observability = SpyObservability()
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="", tool_calls=[_tool_call("history")], finish_reason="tool_calls"),
            LlmResponse(content="<reply><message><text>done</text></message></reply>", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=observability,
    )
    registry = SessionRegistry(max_turns=3)
    session = registry.create(session_id="private_1", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == "<reply><message><text>done</text></message></reply>"
    assert len(observability.started) == 1
    assert observability.started[0]["message_count"] == 3
    assert len(observability.generations) == 2
    assert len(observability.tools) == 1
    assert observability.tools[0]["status"] == "ok"
    assert len(observability.success) == 1
    assert observability.errors == []


def test_agent_reports_failed_tool_span_but_can_continue() -> None:
    observability = SpyObservability()
    llm = StubLlmClient(
        responses=[
            LlmResponse(content="", tool_calls=[_tool_call("fail_tool")], finish_reason="tool_calls"),
            LlmResponse(content="<reply><message><text>fallback</text></message></reply>", tool_calls=[], finish_reason="stop"),
        ]
    )
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        max_retries=1,
        temperature=0.0,
        observability=observability,
    )
    registry = SessionRegistry(max_turns=3)
    session = registry.create(session_id="private_2", metadata={"session_type": "private"})

    reply = agent.run(
        session=session,
        user_message="hello",
    )

    assert reply.output_xml == "<reply><message><text>fallback</text></message></reply>"
    assert len(observability.tools) == 1
    assert observability.tools[0]["status"] == "failed"
    assert len(observability.success) == 1
