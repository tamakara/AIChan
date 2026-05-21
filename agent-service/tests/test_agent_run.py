from agent_service.services.agent_run import AgentRunRegistry


class StubAgentCore:
    def __init__(self) -> None:
        self.calls: list[object] = []

    @property
    def max_turns(self) -> int:
        return 3

    def run(self, context) -> str:
        self.calls.append(context)
        return "ok"


def test_registry_create_generates_unique_agent_id() -> None:
    registry = AgentRunRegistry(agent_core=StubAgentCore())  # type: ignore[arg-type]
    first = registry.create(metadata={"session_id": "s1"})
    second = registry.create(metadata={"session_id": "s2"})

    assert first.get_agent_id() != second.get_agent_id()


def test_registry_get_hit_and_miss() -> None:
    registry = AgentRunRegistry(agent_core=StubAgentCore())  # type: ignore[arg-type]
    agent_run = registry.create(metadata={})

    assert registry.get(agent_run.get_agent_id()) is agent_run
    assert registry.get("missing") is None


def test_agent_run_keeps_metadata_snapshot() -> None:
    registry = AgentRunRegistry(agent_core=StubAgentCore())  # type: ignore[arg-type]
    metadata = {"session_id": "private_1"}
    agent_run = registry.create(metadata=metadata)
    metadata["session_id"] = "mutated"

    assert agent_run.metadata == {"session_id": "private_1"}
