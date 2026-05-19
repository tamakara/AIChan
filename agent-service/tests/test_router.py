from threading import Lock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.router.router import create_router
from agent_service.services.types.session import Session


class StubAgentCore:
    def __init__(self) -> None:
        self.calls: list[tuple[Session, str]] = []
        self.fail: bool = False

    def run(self, session: Session, user_message: str) -> str:
        self.calls.append((session, user_message))
        if self.fail:
            raise RuntimeError("stub failure")
        return f"echo:{user_message}"


def build_client(
    agent: StubAgentCore,
    session_contexts: dict[str, tuple[Session, object]] | None = None,
    registry_lock: object | None = None,
) -> TestClient:
    contexts = session_contexts if session_contexts is not None else {}
    app = FastAPI()
    app.include_router(
        create_router(
            agent=agent,
            session_contexts=contexts,
            registry_lock=registry_lock or Lock(),
        )
    )
    return TestClient(app)


def test_healthz() -> None:
    client = build_client(StubAgentCore())
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_creates_session_and_injects_system_prompt() -> None:
    agent = StubAgentCore()
    session_contexts: dict[str, tuple[Session, Lock]] = {}
    client = build_client(agent=agent, session_contexts=session_contexts)

    response = client.post(
        "/chat",
        json={"session_id": "private_1", "user_message": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["reply"] == "echo:hello"
    assert len(agent.calls) == 1

    called_session, called_message = agent.calls[0]
    assert called_message == "hello"
    assert called_session.get_session_id() == "private_1"
    assert "private_1" in session_contexts

    # 会话首次创建时必须注入 system prompt 与 session_start，
    # 否则后续多轮推理会丢失统一行为边界与会话标识。
    session_messages = called_session.get_messages()
    assert len(session_messages) == 2
    assert session_messages[0]["role"] == "system"
    assert session_messages[1]["role"] == "system"
    assert "<session_start session_id=private_1>" in str(session_messages[1]["content"])


def test_chat_reuses_existing_session() -> None:
    agent = StubAgentCore()
    session_contexts: dict[str, tuple[Session, Lock]] = {}
    client = build_client(agent=agent, session_contexts=session_contexts)

    first = client.post(
        "/chat",
        json={"session_id": "private_1", "user_message": "hello"},
    )
    second = client.post(
        "/chat",
        json={"session_id": "private_1", "user_message": "again"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(agent.calls) == 2

    # 同一 session_id 必须命中同一个 Session 对象，
    # 这是跨请求保留对话历史的前提。
    assert agent.calls[0][0] is agent.calls[1][0]
    assert list(session_contexts.keys()) == ["private_1"]


def test_chat_returns_500_when_agent_fails() -> None:
    agent = StubAgentCore()
    agent.fail = True
    client = build_client(agent=agent)

    response = client.post(
        "/chat",
        json={"session_id": "private_1", "user_message": "hello"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "stub failure"
