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
        if path.endswith("/memory"):
            user_id = path.split("/")[-2]
            params = params or {}
            start_line = int(params.get("start_line", 0))
            line_count = int(params.get("line_count", 200))
            return StubResponse(
                payload={
                    "user_id": user_id,
                    "content_markdown": "## 用户画像\n\n## 相关记忆\n",
                    "start_line": start_line,
                    "line_count": line_count,
                    "total_lines": 3,
                    "has_more": False,
                }
            )
        return StubResponse(payload={"ok": True, "data": {"messages": []}})

    async def post(self, path: str, json: dict | None = None):
        self.requests.append((self.base_url, path, json))
        return StubResponse(payload={"ok": True, "result": {"value": 1}})


@pytest.fixture(autouse=True)
def patch_async_client(monkeypatch):
    StubAsyncClient.requests = []
    monkeypatch.setattr(client_module.httpx, "AsyncClient", StubAsyncClient)


@pytest.mark.asyncio
async def test_file_methods_call_hub_file_api() -> None:
    client = ToolMcpClient(
        hub_base_url="http://hub",
        file_base_url="http://file",
        memory_base_url="http://memory",
        timeout_seconds=5,
    )

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


@pytest.mark.asyncio
async def test_get_user_memory_calls_memory_service_raw_api() -> None:
    client = ToolMcpClient(
        hub_base_url="http://hub",
        file_base_url="http://file",
        memory_base_url="http://memory",
        timeout_seconds=5,
    )

    result = await client.get_user_memory("123", start_line=4, line_count=20)

    assert result == {
        "user_id": "123",
        "content_markdown": "## 用户画像\n\n## 相关记忆\n",
        "start_line": 4,
        "line_count": 20,
        "total_lines": 3,
        "has_more": False,
    }
    assert StubAsyncClient.requests == [
        ("http://memory", "/api/v1/users/123/memory", {"start_line": 4, "line_count": 20}),
    ]


@pytest.mark.asyncio
async def test_adapter_invoke_calls_generic_hub_api() -> None:
    client = ToolMcpClient(
        hub_base_url="http://hub", file_base_url="http://file",
        memory_base_url="http://memory", timeout_seconds=5,
    )
    result = await client.adapter_invoke("qq:main:group:1", "user.get", {"user_id": "2"})
    assert result == {"value": 1}
