from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_service.router.router import create_router


class StubConnectionState:
    def get(self):
        return object()


class StubNapcatWs:
    async def handle_connection(self, websocket) -> None:
        return

    async def send_action(self, action: str, params: dict) -> dict:
        if action == "get_stranger_info":
            return {"status": "ok", "retcode": 0, "data": {"user_id": params["user_id"]}}
        return {
            "status": "ok",
            "retcode": 0,
            "data": {"messages": [{"message_id": 9, "message": []}]},
        }


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_router(
            napcat_ws_gateway=StubNapcatWs(),  # type: ignore[arg-type]
            napcat_connection_state=StubConnectionState(),  # type: ignore[arg-type]
        )
    )
    return TestClient(app)


def test_healthz() -> None:
    client = build_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_user_info_proxy_uses_napcat_action() -> None:
    client = build_client()
    response = client.get("/api/v1/user/123/info")
    assert response.status_code == 200
    assert response.json()["data"]["data"]["user_id"] == 123


def test_message_history_proxy_normalizes_next_cursor() -> None:
    client = build_client()
    response = client.get("/api/v1/message/history?message_type=private&peer_id=123")
    assert response.status_code == 200
    assert response.json()["data"]["next_before_message_id"] == 9
