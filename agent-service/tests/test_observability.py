from __future__ import annotations

from dataclasses import dataclass

from agent_service.config import LangfuseSettings
from agent_service.services.observability import LangfuseObservability, RunTrace


@dataclass
class FakeObservation:
    name: str
    as_type: str
    input: object
    output: object
    metadata: dict | None
    model: str | None

    def __post_init__(self) -> None:
        self.children: list[FakeObservation] = []
        self.updates: list[dict] = []

    def start_as_current_observation(
        self,
        *,
        name: str,
        as_type: str,
        input: object = None,
        output: object = None,
        metadata: dict | None = None,
        model: str | None = None,
    ) -> "FakeContextManager":
        child = FakeObservation(
            name=name,
            as_type=as_type,
            input=input,
            output=output,
            metadata=metadata,
            model=model,
        )
        self.children.append(child)
        return FakeContextManager(child)

    def update(self, **kwargs) -> None:
        self.updates.append(kwargs)


@dataclass
class FakeContextManager:
    observation: FakeObservation

    def __enter__(self) -> FakeObservation:
        return self.observation

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.roots: list[FakeObservation] = []
        self.flush_called = 0

    def start_as_current_observation(self, **kwargs) -> FakeContextManager:
        root = FakeObservation(
            name=kwargs["name"],
            as_type=kwargs["as_type"],
            input=kwargs.get("input"),
            output=kwargs.get("output"),
            metadata=kwargs.get("metadata"),
            model=kwargs.get("model"),
        )
        self.roots.append(root)
        return FakeContextManager(root)

    def flush(self) -> None:
        self.flush_called += 1


class FailingLangfuseClient:
    def start_as_current_observation(self, **kwargs):
        raise RuntimeError("start failed")

    def flush(self) -> None:
        raise RuntimeError("flush failed")


def _settings() -> LangfuseSettings:
    return LangfuseSettings(
        enabled=True,
        host="https://cloud.langfuse.com",
        public_key="pk",
        secret_key="sk",
        flush_at=16,
        flush_interval=0.5,
        request_timeout=5.0,
    )


def test_langfuse_observability_records_root_generation_tool_and_finish() -> None:
    client = FakeLangfuseClient()
    observability = LangfuseObservability(settings=_settings(), client=client)

    run = observability.start_run(
        agent_id="agent_1",
        message_count=2,
        max_turns=5,
        agent_run_metadata={"session_id": "private_1"},
    )
    observability.llm_generation(
        run=run,
        turn=1,
        input_messages=[{"role": "user", "content": "hi"}],  # type: ignore[list-item]
        output_content="hello",
        output_tool_calls=[],
        finish_reason="stop",
        model="gpt",
        duration_ms=12,
    )
    observability.tool_span(
        run=run,
        turn=1,
        tool_name="history",
        tool_args={"limit": 3},
        status="ok",
        error=None,
        duration_ms=7,
        output='{"ok":true}',
    )
    observability.finish_run_success(run=run, reply="done", duration_ms=20)
    observability.flush(timeout_seconds=0.2)

    assert len(client.roots) == 1
    root = client.roots[0]
    assert root.name == "agent.chat.run"
    assert root.metadata["agent_id"] == "agent_1"
    assert root.metadata["message_count"] == 2
    assert root.metadata["agent_run_metadata"] == {"session_id": "private_1"}
    assert len(root.children) == 2
    assert root.children[0].as_type == "generation"
    assert root.children[1].as_type == "tool"
    assert root.updates[-1]["output"] == "done"
    assert client.flush_called == 1


def test_langfuse_observability_failures_are_swallowed() -> None:
    observability = LangfuseObservability(settings=_settings(), client=FailingLangfuseClient())

    run = observability.start_run(
        agent_id="agent_1",
        message_count=1,
        max_turns=3,
        agent_run_metadata={},
    )
    observability.llm_generation(
        run=run,
        turn=1,
        input_messages=[],
        output_content="",
        output_tool_calls=[],
        finish_reason="stop",
        model="gpt",
        duration_ms=1,
    )
    observability.tool_span(
        run=run,
        turn=1,
        tool_name="history",
        tool_args={},
        status="failed",
        error="x",
        duration_ms=1,
        output=None,
    )
    observability.finish_run_error(run=run, error="boom", duration_ms=3)
    observability.flush(timeout_seconds=0.1)

    assert isinstance(run, RunTrace)
