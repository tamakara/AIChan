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
    requests: list[tuple[str, dict | None]] = []

    def __init__(self, *args, **kwargs) -> None:
        return

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        return

    async def get(self, path: str, params: dict | None = None):
        self.requests.append((path, params))
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
    client = ToolMcpClient(base_url="http://hub", timeout_seconds=5)

    metadata = await client.get_file_metadata("qq/private/1/9/0-abc.txt")
    text = await client.read_file_text("qq/private/1/9/0-abc.txt", max_chars=20)
    content = await client.get_file_content("qq/private/1/9/0-abc.txt")

    assert metadata["mime"] == "text/plain"
    assert text["text"] == "hello"
    assert content == b"image"
    assert StubAsyncClient.requests == [
        ("/api/v1/files/qq/private/1/9/0-abc.txt/metadata", None),
        ("/api/v1/files/qq/private/1/9/0-abc.txt/text", {"max_chars": 20}),
        ("/api/v1/files/qq/private/1/9/0-abc.txt/content", None),
    ]
