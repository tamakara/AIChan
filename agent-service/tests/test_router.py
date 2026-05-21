from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.router.router import create_router
from agent_service.services.agent_run import AgentRunRegistry


class StubAgentCore:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.fail: bool = False

    @property
    def max_turns(self) -> int:
        return 3

    def run(self, context) -> str:
        self.calls.append(context)
        if self.fail:
            raise RuntimeError("stub failure")
        user_message = context.messages[-1]["content"]
        return f"echo:{user_message}"


def build_client(agent: StubAgentCore, registry: AgentRunRegistry | None = None) -> TestClient:
    app = FastAPI()
    agent_run_registry = registry or AgentRunRegistry(agent_core=agent)  # type: ignore[arg-type]
    app.include_router(
        create_router(
            agent_run_registry=agent_run_registry,
        )
    )
    return TestClient(app)


def _create_agent_run(client: TestClient, metadata: dict | None = None) -> str:
    response = client.post("/agent-runs", json={} if metadata is None else {"metadata": metadata})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("agent_id"), str)
    return data["agent_id"]


def test_healthz() -> None:
    client = build_client(StubAgentCore())
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_agent_run_returns_metadata_and_agent_id() -> None:
    client = build_client(StubAgentCore())

    response = client.post("/agent-runs", json={"metadata": {"session_id": "private_1"}})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["agent_id"], str)
    assert payload["metadata"] == {"session_id": "private_1"}


def test_create_agent_run_without_metadata_defaults_to_empty_dict() -> None:
    client = build_client(StubAgentCore())

    response = client.post("/agent-runs", json={})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["agent_id"], str)
    assert payload["metadata"] == {}


def test_chat_returns_404_when_agent_not_created() -> None:
    client = build_client(StubAgentCore())

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
    agent = StubAgentCore()
    registry = AgentRunRegistry(agent_core=agent)  # type: ignore[arg-type]
    client = build_client(agent=agent, registry=registry)
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
    assert response.json()["reply"].startswith("echo:<chat_messages")
    assert len(agent.calls) == 1

    called_context = agent.calls[0]
    called_messages = called_context.messages
    called_message = str(called_messages[-1]["content"])
    assert "<chat_messages session_id=\"private_1\" agent_id=" in called_message
    assert "<message user_id=\"qq_1\" event_time=\"1710000000\">hello</message>" in called_message

    # 创建时注入两条 system（提示词 + session_start），首次请求后追加 user/assistant。
    assert len(called_messages) == 4
    assert called_messages[0]["role"] == "system"
    assert called_messages[1]["role"] == "system"
    assert called_messages[2]["role"] == "user"
    assert called_messages[3]["role"] == "assistant"
    assert (
        f'<session_start agent_id="{agent_id}" session_id="private_1">'
        in str(called_messages[1]["content"])
    )


def test_chat_reuses_existing_agent_run() -> None:
    agent = StubAgentCore()
    client = build_client(agent=agent)
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
    assert len(agent.calls) == 2
    assert agent.calls[0] is agent.calls[1]


def test_chat_returns_500_when_agent_fails() -> None:
    agent = StubAgentCore()
    agent.fail = True
    client = build_client(agent=agent)
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
    client = build_client(StubAgentCore())
    agent_id = _create_agent_run(client)

    response = client.post(
        "/chat",
        json={"agent_id": agent_id, "messages": []},
    )

    assert response.status_code == 422


def test_chat_returns_422_when_legacy_extra_fields_passed() -> None:
    client = build_client(StubAgentCore())
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
