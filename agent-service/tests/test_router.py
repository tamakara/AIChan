from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_service.router.router import create_router
from agent_service.services.agent import Agent
from agent_service.services.session import SessionRegistry
from agent_service.services.observability import NoopObservability
from agent_service.services.types.llm import LlmResponse


class StubLlmClient:
    def __init__(self) -> None:
        self.calls: list[list] = []
        self.fail: bool = False
        self.output: str | None = None
        self.model_name = "gpt-test"

    def generate(self, messages, tools_schema, temperature) -> LlmResponse:
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("stub failure")
        reply = self.output if self.output is not None else "<reply><text>ok</text></reply>"
        return LlmResponse(content=reply, tool_calls=[], finish_reason="stop")


class StubMcpGateway:
    def get_tools_schema(self):
        return []

    def call_tool(self, tool_name: str, tool_args: dict) -> str:
        return '{"ok": true}'


def build_client(
    llm_client: StubLlmClient,
    agent: Agent | None = None,
    registry: SessionRegistry | None = None,
) -> TestClient:
    app = FastAPI()
    _agent = agent or Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    _registry = registry or SessionRegistry(max_turns=3)
    app.include_router(create_router(agent=_agent, session_registry=_registry))
    return TestClient(app)


def _create_session(client: TestClient, metadata: dict | None = None) -> str:
    response = client.post("/sessions", json={} if metadata is None else {"metadata": metadata})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data.get("session_id"), str)
    return data["session_id"]


def test_healthz() -> None:
    client = build_client(StubLlmClient())
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_session_returns_metadata_and_session_id() -> None:
    client = build_client(StubLlmClient())

    response = client.post("/sessions", json={"metadata": {"session_id": "private_1"}})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["session_id"], str)
    assert payload["metadata"] == {"session_id": "private_1"}


def test_create_session_without_metadata_defaults_to_empty_dict() -> None:
    client = build_client(StubLlmClient())

    response = client.post("/sessions", json={})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["session_id"], str)
    assert payload["metadata"] == {"session_id": payload["session_id"]}


def test_delete_session() -> None:
    client = build_client(StubLlmClient())
    session_id = _create_session(client)

    response = client.delete(f"/sessions/{session_id}")

    assert response.status_code == 200
    assert response.json()["deleted"] is True

    response = client.delete(f"/sessions/{session_id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


def test_delete_session_returns_404_for_unknown() -> None:
    client = build_client(StubLlmClient())

    response = client.delete("/sessions/unknown")

    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


def test_queue_message_adds_message_to_existing_session() -> None:
    client = build_client(StubLlmClient())
    session_id = _create_session(client)

    response = client.post(
        f"/sessions/{session_id}/queue-message",
        json={"input_xml": "<messages><message><text>queued</text></message></messages>"},
    )

    assert response.status_code == 200
    assert response.json() == {"queued": True}


def test_queue_message_returns_404_for_unknown_session() -> None:
    client = build_client(StubLlmClient())

    response = client.post(
        "/sessions/missing/queue-message",
        json={"input_xml": "<messages />"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


def test_chat_returns_404_when_session_not_created() -> None:
    client = build_client(StubLlmClient())

    response = client.post(
        "/chat",
        json={"session_id": "not-created", "input_xml": "<messages />"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "session not found"


def test_chat_uses_existing_session_and_injects_context() -> None:
    llm_client = StubLlmClient()
    registry = SessionRegistry(max_turns=3)
    agent = Agent(  # type: ignore[arg-type]
        llm_client=llm_client,
        mcp_gateway=StubMcpGateway(),
        max_turns=3,
        temperature=0.0,
        observability=NoopObservability(),
    )
    client = build_client(llm_client=llm_client, agent=agent, registry=registry)
    session_id = _create_session(client, {"session_id": "private_1"})

    response = client.post(
        "/chat",
        json={"session_id": session_id, "input_xml": "<messages><message><text>hello</text></message></messages>"},
    )

    assert response.status_code == 200
    assert response.json() == {"output_xml": "<reply><text>ok</text></reply>"}
    assert len(llm_client.calls) == 1

    called_messages = llm_client.calls[0]
    assert called_messages[-2]["content"] == '<turn index="1" />'
    assert called_messages[-1]["content"] == "<messages><message><text>hello</text></message></messages>"

    # Session 内保留角色提示词和会话信息两条 system 消息，再追加用户消息和当前 turn。
    assert len(called_messages) == 4
    assert called_messages[0]["role"] == "system"
    assert called_messages[1]["role"] == "system"
    assert called_messages[2]["role"] == "system"
    assert called_messages[3]["role"] == "user"

    session = registry.get(session_id)
    assert session is not None
    persisted_messages = session._context.messages  # noqa: SLF001
    assert len(persisted_messages) == 5
    assert persisted_messages[4]["role"] == "assistant"


def test_chat_reuses_existing_session() -> None:
    llm_client = StubLlmClient()
    client = build_client(llm_client=llm_client)
    session_id = _create_session(client, {"session_id": "private_1"})

    first = client.post(
        "/chat",
        json={"session_id": session_id, "input_xml": "<messages><message><text>hello</text></message></messages>"},
    )
    second = client.post(
        "/chat",
        json={"session_id": session_id, "input_xml": "<messages><message><text>again</text></message></messages>"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(llm_client.calls) == 2
    assert llm_client.calls[0] is not llm_client.calls[1]

    first_user_xml = str(llm_client.calls[0][-1]["content"])
    second_call_roles = [msg["role"] for msg in llm_client.calls[1]]
    second_call_contents = [str(msg["content"]) for msg in llm_client.calls[1]]

    assert second_call_roles == ["system", "system", "system", "user", "assistant", "system", "user"]
    assert first_user_xml in second_call_contents
    assert "<reply><text>ok</text></reply>" in second_call_contents


def test_chat_returns_fallback_when_agent_fails() -> None:
    llm_client = StubLlmClient()
    llm_client.fail = True
    client = build_client(llm_client=llm_client)
    session_id = _create_session(client, {"session_id": "private_1"})

    response = client.post(
        "/chat",
        json={"session_id": session_id, "input_xml": "<messages />"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "output_xml": "<reply><text>笨蛋，刚才脑袋短路了一下，稍后再试试喵。</text></reply>"
    }


def test_chat_returns_422_when_input_xml_empty() -> None:
    client = build_client(StubLlmClient())
    session_id = _create_session(client)

    response = client.post("/chat", json={"session_id": session_id, "input_xml": ""})

    assert response.status_code == 422


def test_chat_wraps_non_xml_llm_output() -> None:
    llm_client = StubLlmClient()
    llm_client.output = "plain < text"
    client = build_client(llm_client=llm_client)
    session_id = _create_session(client)

    response = client.post(
        "/chat",
        json={"session_id": session_id, "input_xml": "<messages />"},
    )

    assert response.status_code == 200
    assert response.json() == {"output_xml": "<reply><text>plain &lt; text</text></reply>"}


def test_chat_returns_422_when_legacy_extra_fields_passed() -> None:
    client = build_client(StubLlmClient())
    session_id = _create_session(client)

    response = client.post(
        "/chat",
        json={
            "session_id": session_id,
            "input_xml": "<messages />",
            "batch": "hello",
            "messages": [{"user_id": "qq_1", "content": "legacy"}],
            "metadata": {"session_id": "legacy"},
        },
    )

    assert response.status_code == 422
