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
    assert response.json() == {
        "user_id": "123",
        "content_markdown": USER_MEMORY_EMPTY_TEMPLATE,
        "start_line": 0,
        "line_count": 200,
        "total_lines": 3,
        "has_more": False,
    }


def test_get_user_memory_returns_requested_page_with_metadata(tmp_path: Path) -> None:
    client = build_client(tmp_path)
    (tmp_path / "users").mkdir(parents=True, exist_ok=True)
    (tmp_path / "users" / "123.md").write_text(
        "## 用户画像\n- A\n\n## 相关记忆\n- B\n- C\n",
        encoding="utf-8",
    )

    response = client.get("/api/v1/users/123/memory", params={"start_line": 2, "line_count": 2})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "123",
        "content_markdown": "\n## 相关记忆\n",
        "start_line": 2,
        "line_count": 2,
        "total_lines": 6,
        "has_more": True,
    }


def test_get_user_memory_returns_empty_page_when_start_line_exceeds_total_lines(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    response = client.get("/api/v1/users/123/memory", params={"start_line": 10, "line_count": 5})

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "123",
        "content_markdown": "",
        "start_line": 10,
        "line_count": 5,
        "total_lines": 3,
        "has_more": False,
    }


def test_get_user_memory_rejects_invalid_pagination_query(tmp_path: Path) -> None:
    client = build_client(tmp_path)

    negative_start = client.get("/api/v1/users/123/memory", params={"start_line": -1})
    zero_count = client.get("/api/v1/users/123/memory", params={"line_count": 0})

    assert negative_start.status_code == 422
    assert zero_count.status_code == 422
