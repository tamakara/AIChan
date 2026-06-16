import pytest

import hub_service.services.media_storage as media_storage_module
from hub_service.config import FileServiceSettings
from hub_service.services.media_storage import MediaStorage


class StubResponse:
    def __init__(self, *, payload=None, content=b"") -> None:
        self._payload = payload
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return

    def json(self):
        return self._payload


class StubAsyncClient:
    requests: list[tuple[str, str, dict | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return

    async def request(self, method: str, path: str, json: dict | None = None):
        self.requests.append((method, path, json))
        return StubResponse(
            payload={
                "ok": True,
                "data": {
                    "object_key": "a" * 64,
                    "name": "note.txt",
                    "mime": "text/plain",
                    "size": 5,
                    "sha256": "a" * 64,
                },
            }
        )

    async def get(self, path: str):
        self.requests.append(("GET", path, None))
        return StubResponse(content=b"hello")


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch) -> None:
    StubAsyncClient.requests = []
    monkeypatch.setattr(media_storage_module.httpx, "AsyncClient", StubAsyncClient)


@pytest.mark.asyncio
async def test_store_segment_delegates_url_to_file_service() -> None:
    storage = MediaStorage(FileServiceSettings(base_url="http://file-service:8040", timeout_seconds=5))

    record = await storage.store_segment(
        event={"message_id": 1},
        segment_type="file",
        segment_index=0,
        data={"url": "https://download.test/file", "name": "note.txt"},
    )

    assert record.object_key == "a" * 64
    assert StubAsyncClient.requests == [
        (
            "POST",
            "/api/v1/files/from-url",
            {"url": "https://download.test/file", "name": "note.txt", "kind": "file"},
        )
    ]
