from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from memory_service.router import create_router
from memory_service.services.memory import USER_MEMORY_EMPTY_TEMPLATE, MemoryService


class StubCompressor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def compress(self, messages_text: str) -> str:
        self.calls.append(messages_text)
        return "- 用户偏好直接结论"


def build_client(tmp_path: Path, compressor: StubCompressor | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_router(
            memory_service=MemoryService(
                root_dir=tmp_path,
                compressor=compressor or StubCompressor(),
            )
        )
    )
    return TestClient(app)


def test_healthz(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_missing_memory_returns_empty(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/memories/private_1")

    assert response.status_code == 200
    assert response.json() == {"session_id": "private_1", "content_markdown": ""}


def test_post_compress_returns_full_content_and_added_summary(tmp_path: Path) -> None:
    compressor = StubCompressor()
    client = build_client(tmp_path, compressor=compressor)

    response = client.post(
        "/api/v1/memories/private_1/compress",
        json={"messages_text": "user: 记住我喜欢直接结论"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": "private_1",
        "content_markdown": "- 用户偏好直接结论\n",
        "added_markdown": "- 用户偏好直接结论",
        "added_count": 1,
    }
    assert compressor.calls == ["user: 记住我喜欢直接结论"]


def test_get_missing_user_memory_returns_empty_template(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/users/123/memory")

    assert response.status_code == 200
    assert response.json() == {"user_id": "123", "content_markdown": USER_MEMORY_EMPTY_TEMPLATE}
