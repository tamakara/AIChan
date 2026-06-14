from fastapi import FastAPI
from fastapi.testclient import TestClient

from file_service.router.router import create_router
from file_service.services.storage import FileNotFoundError, FileRecord, UnsupportedTextFileError


class StubFileStorage:
    async def store_url(self, *, url, name, mime, kind) -> FileRecord:
        return FileRecord(object_key="a" * 64, name=name or "file.txt", mime="text/plain", size=5, sha256="a" * 64)

    async def metadata(self, object_key: str) -> FileRecord:
        return FileRecord(object_key=object_key, name="file.txt", mime="text/plain", size=5, sha256=object_key)

    async def content(self, object_key: str) -> bytes:
        return b"hello"

    async def text(self, object_key: str, max_chars: int) -> tuple[str, bool]:
        if object_key == "b" * 64:
            raise UnsupportedTextFileError(object_key)
        if object_key == "c" * 64:
            raise FileNotFoundError(object_key)
        return "hello"[:max_chars], False


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(create_router(file_storage=StubFileStorage()))  # type: ignore[arg-type]
    return TestClient(app)


def test_store_from_url_returns_sha_object_key() -> None:
    client = build_client()
    response = client.post("/api/v1/files/from-url", json={"url": "https://example.test/a.txt", "name": "a.txt"})

    assert response.status_code == 200
    assert response.json()["data"]["object_key"] == "a" * 64


def test_file_content_returns_bytes() -> None:
    client = build_client()
    response = client.get(f"/api/v1/files/{'a' * 64}/content")

    assert response.status_code == 200
    assert response.content == b"hello"


def test_file_text_rejects_non_text_file() -> None:
    client = build_client()
    response = client.get(f"/api/v1/files/{'b' * 64}/text")

    assert response.status_code == 422
