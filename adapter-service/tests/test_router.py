from fastapi.testclient import TestClient

from adapter_service.router.router import create_router
from adapter_service.services.connection_state import NapcatConnectionState


class StubAdapterService:
    def build_get_user_info_action(self, abstract_user_id):
        if abstract_user_id == "bad":
            raise ValueError("bad user")
        return type("Action", (), {"action": "get_stranger_info", "params": {"user_id": 9}})()

    def build_get_history_action(self, session_id, limit, before_message_id):
        if session_id == "bad":
            raise ValueError("bad session")
        return type(
            "Action",
            (),
            {
                "action": "get_group_msg_history",
                "params": {"group_id": 9, "count": limit, "message_seq": before_message_id or 0},
            },
        )()

    def normalize_history_result(self, session_id, raw_result):
        return {
            "session_id": session_id,
            "messages": [{"message_id": 1, "text": "hello"}],
            "next_before_message_id": 1,
        }


class StubGateway:
    async def handle_connection(self, websocket):
        return None

    async def send_action(self, websocket, action, params):
        if action == "timeout":
            raise TimeoutError("timeout")
        return {"status": "ok", "retcode": 0, "data": {"message_id": 88, "action": action, "params": params}}


def build_client(service: StubAdapterService, gateway: StubGateway, state: NapcatConnectionState) -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(
        create_router(
            adapter_service=service,
            napcat_ws_gateway=gateway,
            napcat_connection_state=state,
        )
    )
    return TestClient(app)


def test_healthz() -> None:
    client = build_client(StubAdapterService(), StubGateway(), NapcatConnectionState())
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_user_info_requires_ws_connection() -> None:
    client = build_client(StubAdapterService(), StubGateway(), NapcatConnectionState())
    response = client.get("/api/v1/user/qq_1/info")
    assert response.status_code == 503


def test_get_user_info_validation() -> None:
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    client = build_client(StubAdapterService(), StubGateway(), state)
    response = client.get("/api/v1/user/bad/info")
    assert response.status_code == 422


def test_get_message_history_requires_ws_connection() -> None:
    client = build_client(StubAdapterService(), StubGateway(), NapcatConnectionState())
    response = client.get("/api/v1/message/history", params={"session_id": "private_1", "limit": 5})
    assert response.status_code == 503


def test_get_message_history_validation() -> None:
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    client = build_client(StubAdapterService(), StubGateway(), state)
    response = client.get("/api/v1/message/history", params={"session_id": "bad", "limit": 5})
    assert response.status_code == 422

