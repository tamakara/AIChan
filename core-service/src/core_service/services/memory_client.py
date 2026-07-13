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

    async def get_user_memory(self, user_id: str, *, start_line: int, line_count: int) -> dict[str, object]:
        response = await self._client.get(
            f"/api/v1/users/{quote(user_id, safe='')}/memory",
            params={"start_line": start_line, "line_count": line_count},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("memory-service 返回了非法用户记忆")
        return payload
