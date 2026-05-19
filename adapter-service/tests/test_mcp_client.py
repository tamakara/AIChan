from __future__ import annotations

import asyncio

import httpx
import pytest

from adapter_service.mcp.client import AdapterClient


def test_get_message_history_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "ok": True,
                "data": {"session_id": "private_1", "messages": [{"message_id": 1}]},
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path, params=None):
            return FakeResponse()

    monkeypatch.setattr("adapter_service.mcp.client.httpx.AsyncClient", FakeAsyncClient)

    async def run() -> None:
        client = AdapterClient("http://adapter", 5)
        data = await client.get_message_history("private_1", 20, None)
        assert data["session_id"] == "private_1"
        assert data["messages"][0]["message_id"] == 1

    asyncio.run(run())


def test_get_message_history_http_error_with_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "http://adapter/api/v1/message/history")
    response = httpx.Response(
        status_code=422,
        request=request,
        json={"detail": "invalid session"},
    )

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, path, params=None):
            raise httpx.HTTPStatusError("bad request", request=request, response=response)

    monkeypatch.setattr("adapter_service.mcp.client.httpx.AsyncClient", FakeAsyncClient)

    async def run() -> None:
        client = AdapterClient("http://adapter", 5)
        with pytest.raises(RuntimeError, match="status=422"):
            await client.get_message_history("private_1", 20, None)

    asyncio.run(run())

