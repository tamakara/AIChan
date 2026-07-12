from typing import Any

import httpx


class FileServiceClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.request(method, path, **kwargs)
