from agent_service.services.agent_run import AgentRunRegistry
from agent_service.services.observability import NoopObservability
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self) -> None:
        self.model_name = "gpt-test"
        self.calls: list[object] = []

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append((messages, tools_schema, temperature))
        return LlmResponse(content="ok", tool_calls=[], finish_reason="stop")


class StubMcpGateway:
    def get_tools_schema(self):
        return []

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        return '{"ok": true}'


def _build_registry() -> AgentRunRegistry:
    return AgentRunRegistry(  # type: ignore[arg-type]
        llm_client=StubLlmClient(),
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )


def test_registry_create_generates_unique_agent_id() -> None:
    registry = _build_registry()
    first = registry.create(metadata={"session_id": "s1"})
    second = registry.create(metadata={"session_id": "s2"})

    assert first.get_agent_id() != second.get_agent_id()


def test_registry_get_hit_and_miss() -> None:
    registry = _build_registry()
    agent_run = registry.create(metadata={})

    assert registry.get(agent_run.get_agent_id()) is agent_run
    assert registry.get("missing") is None


def test_agent_run_keeps_metadata_snapshot() -> None:
    registry = _build_registry()
    metadata = {"session_id": "private_1"}
    agent_run = registry.create(metadata=metadata)
    metadata["session_id"] = "mutated"

    assert agent_run.metadata == {"session_id": "private_1"}
