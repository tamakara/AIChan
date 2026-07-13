import os
import asyncio
import time
from pathlib import Path

import httpx
import pytest

from core_service.services.file_cache import FileCache


@pytest.mark.asyncio
async def test_file_cache_downloads_once_with_adapter_token(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await asyncio.sleep(0.01)
        assert request.headers["authorization"] == "Bearer secret"
        assert request.url.raw_path.endswith(b"/ref%3A1")
        return httpx.Response(200, content=b"hello", headers={"content-type": "text/plain", "content-disposition": 'attachment; filename="hello.txt"'})

    cache = FileCache(root_dir=tmp_path, ttl_seconds=60, cleanup_interval_seconds=60, max_file_bytes=1024, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await cache.start()
    first, second = await asyncio.gather(
        cache.get(adapter_key=("qq", "main"), file_ref="ref:1", base_url="http://adapter/files", token="secret"),
        cache.get(adapter_key=("qq", "main"), file_ref="ref:1", base_url="http://adapter/files", token="secret"),
    )
    assert first == second
    assert first.path.read_bytes() == b"hello"
    assert first.name == "hello.txt"
    assert len(requests) == 1
    await cache.close()


@pytest.mark.asyncio
async def test_file_cache_enforces_size_and_cleans_expired_files(tmp_path: Path) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"too-large", headers={"content-type": "application/octet-stream"})

    cache = FileCache(root_dir=tmp_path, ttl_seconds=1, cleanup_interval_seconds=60, max_file_bytes=3, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await cache.start()
    with pytest.raises(ValueError, match="大小限制"):
        await cache.get(adapter_key=("qq", "main"), file_ref="large", base_url="http://adapter/files", token="secret")
    expired = tmp_path / "expired"
    expired.write_bytes(b"x")
    os.utime(expired, (time.time() - 5, time.time() - 5))
    await cache.cleanup()
    assert not expired.exists()
    await cache.close()
