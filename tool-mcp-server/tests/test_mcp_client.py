import pytest

import tool_mcp_server.mcp.client as client_module
from tool_mcp_server.mcp.client import ToolMcpClient


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
    requests: list[tuple[str | None, str, dict | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        self.base_url = kwargs.get("base_url")
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return

    async def get(self, path: str, params: dict | None = None):
        self.requests.append((self.base_url, path, params))
        if path.endswith("/metadata"):
            return StubResponse(payload={"ok": True, "data": {"object_key": "k", "mime": "text/plain"}})
        if path.endswith("/text"):
            return StubResponse(payload={"ok": True, "data": {"object_key": "k", "text": "hello"}})
        if path.endswith("/content"):
            return StubResponse(content=b"image")
        return StubResponse(payload={"ok": True, "data": {"messages": []}})


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch):
    StubAsyncClient.requests = []
    monkeypatch.setattr(client_module.httpx, "AsyncClient", StubAsyncClient)


@pytest.mark.asyncio
async def test_file_methods_call_hub_file_api() -> None:
    client = ToolMcpClient(qq_base_url="http://hub", file_base_url="http://file", timeout_seconds=5)

    object_key = "a" * 64
    metadata = await client.get_file_metadata(object_key)
    text = await client.read_file_text(object_key, max_chars=20)
    content = await client.get_file_content(object_key)

    assert metadata["mime"] == "text/plain"
    assert text["text"] == "hello"
    assert content == b"image"
    assert StubAsyncClient.requests == [
        ("http://file", f"/api/v1/files/{object_key}/metadata", None),
        ("http://file", f"/api/v1/files/{object_key}/text", {"max_chars": 20}),
        ("http://file", f"/api/v1/files/{object_key}/content", None),
    ]
