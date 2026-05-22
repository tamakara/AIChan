from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.router.router import create_router
from agent_service.services.agent_run import AgentRunRegistry
from agent_service.services.observability import NoopObservability
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self) -> None:
        self.calls: list[list] = []
        self.fail: bool = False
        self.model_name = "gpt-test"

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("stub failure")
        user_message = messages[-1]["content"]
        reply = f"echo:{user_message}"
        return LlmResponse(content=reply, tool_calls=[], finish_reason="stop")


class StubMcpGateway:
    def get_tools_schema(self):
        return []

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        return '{"ok": true}'


def build_client(
    llm_client: StubLlmClient,
    registry: AgentRunRegistry | None = None,
) -> TestClient:
    app = FastAPI()
    agent_run_registry = registry or AgentRunRegistry(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    app.include_router(create_router(agent_run_registry=agent_run_registry))
    return TestClient(app)


def _create_agent_run(client: TestClient, metadata: dict | None = None) -> str:
    response = client.post("/agent-runs", json={} if metadata is None else {"metadata": metadata})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("agent_id"), str)
    return data["agent_id"]


def test_healthz() -> None:
    client = build_client(StubLlmClient())
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_agent_run_returns_metadata_and_agent_id() -> None:
    client = build_client(StubLlmClient())

    response = client.post("/agent-runs", json={"metadata": {"session_id": "private_1"}})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["agent_id"], str)
    assert payload["metadata"] == {"session_id": "private_1"}


def test_create_agent_run_without_metadata_defaults_to_empty_dict() -> None:
    client = build_client(StubLlmClient())

    response = client.post("/agent-runs", json={})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["agent_id"], str)
    assert payload["metadata"] == {}


def test_chat_returns_404_when_agent_not_created() -> None:
    client = build_client(StubLlmClient())

    response = client.post(
        "/chat",
        json={
            "agent_id": "not-created",
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "hello",
                    "event_time": "1710000000",
                }
            ],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "agent_run not found"


def test_chat_uses_existing_agent_run_and_injects_context() -> None:
    llm_client = StubLlmClient()
    registry = AgentRunRegistry(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    client = build_client(llm_client=llm_client, registry=registry)
    agent_id = _create_agent_run(client, {"session_id": "private_1"})

    response = client.post(
        "/chat",
        json={
            "agent_id": agent_id,
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "hello",
                    "event_time": "1710000000",
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["reply"].startswith("echo:<message")
    assert len(llm_client.calls) == 1

    called_messages = llm_client.calls[0]
    called_message = str(called_messages[-1]["content"])
    assert "<chat_messages" not in called_message
    assert called_message == '<message user_id="qq_1" event_time="1710000000">hello</message>'

    # AgentRun 给模型传入的是运行前快照：两条 system + 本轮 user。
    assert len(called_messages) == 3
    assert called_messages[0]["role"] == "system"
    assert called_messages[1]["role"] == "system"
    assert called_messages[2]["role"] == "user"
    assert (
        f'<session_start agent_id="{agent_id}" session_id="private_1">'
        in str(called_messages[1]["content"])
    )

    # AgentRun 负责把 assistant 结果提交回长期上下文。
    persisted_messages = registry.get(agent_id).get_messages()  # type: ignore[union-attr]
    assert len(persisted_messages) == 4
    assert persisted_messages[3]["role"] == "assistant"


def test_chat_reuses_existing_agent_run() -> None:
    llm_client = StubLlmClient()
    client = build_client(llm_client=llm_client)
    agent_id = _create_agent_run(client, {"session_id": "private_1"})

    first = client.post(
        "/chat",
        json={
            "agent_id": agent_id,
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "hello",
                    "event_time": "1710000000",
                }
            ],
        },
    )
    second = client.post(
        "/chat",
        json={
            "agent_id": agent_id,
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "again",
                    "event_time": "1710000001",
                }
            ],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(llm_client.calls) == 2
    assert llm_client.calls[0] is not llm_client.calls[1]

    first_user_xml = str(llm_client.calls[0][-1]["content"])
    second_call_roles = [msg["role"] for msg in llm_client.calls[1]]
    second_call_contents = [str(msg["content"]) for msg in llm_client.calls[1]]

    assert second_call_roles == ["system", "system", "user", "assistant", "user"]
    assert f"echo:{first_user_xml}" in second_call_contents


def test_chat_returns_500_when_agent_fails() -> None:
    llm_client = StubLlmClient()
    llm_client.fail = True
    client = build_client(llm_client=llm_client)
    agent_id = _create_agent_run(client, {"session_id": "private_1"})

    response = client.post(
        "/chat",
        json={
            "agent_id": agent_id,
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "hello",
                    "event_time": "1710000000",
                }
            ],
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "stub failure"


def test_chat_returns_422_when_messages_empty() -> None:
    client = build_client(StubLlmClient())
    agent_id = _create_agent_run(client)

    response = client.post("/chat", json={"agent_id": agent_id, "messages": []})

    assert response.status_code == 422


def test_chat_returns_422_when_legacy_extra_fields_passed() -> None:
    client = build_client(StubLlmClient())
    agent_id = _create_agent_run(client)

    response = client.post(
        "/chat",
        json={
            "agent_id": agent_id,
            "messages": [
                {
                    "user_id": "qq_1",
                    "content": "hello",
                    "event_time": "1710000000",
                    "event_id": "legacy",
                }
            ],
            "metadata": {"session_id": "legacy"},
        },
    )

    assert response.status_code == 422
