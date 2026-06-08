from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_service.router.router import create_router
from hub_service.services.media_storage import StoredMedia, UnsupportedTextFileError


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


class StubMediaStorage:
    async def metadata(self, object_key: str) -> StoredMedia:
        mime = "image/jpeg" if object_key.endswith(".jpg") else "text/plain"
        return StoredMedia(
            object_key=object_key,
            name=object_key.rsplit("/", 1)[-1],
            mime=mime,
            size=5,
            sha256="abc",
        )

    async def content(self, object_key: str) -> bytes:
        return b"hello"

    async def text(self, object_key: str, max_chars: int) -> tuple[str, bool]:
        if object_key.endswith(".jpg"):
            raise UnsupportedTextFileError(object_key)
        return "hello"[:max_chars], False


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(
        create_router(
            napcat_ws_gateway=StubNapcatWs(),  # type: ignore[arg-type]
            napcat_connection_state=StubConnectionState(),  # type: ignore[arg-type]
            media_storage=StubMediaStorage(),  # type: ignore[arg-type]
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


def test_file_metadata_returns_stored_attributes() -> None:
    client = build_client()
    response = client.get("/api/v1/files/qq/private/1/9/0-abc.txt/metadata")
    assert response.status_code == 200
    assert response.json()["data"]["object_key"] == "qq/private/1/9/0-abc.txt"
    assert response.json()["data"]["mime"] == "text/plain"


def test_file_content_returns_bytes() -> None:
    client = build_client()
    response = client.get("/api/v1/files/qq/private/1/9/0-abc.txt/content")
    assert response.status_code == 200
    assert response.content == b"hello"


def test_file_text_rejects_non_text_file() -> None:
    client = build_client()
    response = client.get("/api/v1/files/qq/private/1/9/0-abc.jpg/text")
    assert response.status_code == 422
