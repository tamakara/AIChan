from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class MemoryCompressResult:
    content_markdown: str
    added_markdown: str
    added_count: int


class MemoryClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def read(self, session_id: str) -> str:
        response = await self._client.get(f"/api/v1/memories/{quote(session_id, safe='')}")
        response.raise_for_status()
        return str(response.json().get("content_markdown", ""))

    async def compress(self, session_id: str, messages_text: str) -> MemoryCompressResult:
        response = await self._client.post(
            f"/api/v1/memories/{quote(session_id, safe='')}/compress",
            json={"messages_text": messages_text},
        )
        response.raise_for_status()
        payload = response.json()
        return MemoryCompressResult(
            content_markdown=str(payload.get("content_markdown", "")),
            added_markdown=str(payload.get("added_markdown", "")),
            added_count=int(payload.get("added_count", 0)),
        )
