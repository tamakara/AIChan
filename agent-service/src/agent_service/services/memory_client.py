from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx


@dataclass(frozen=True)
class MemoryCompressResult:
    content_markdown: str
    added_markdown: str
    added_count: int


class MemoryClient(Protocol):
    def read(self, session_id: str) -> str:
        pass

    def compress(self, session_id: str, messages_text: str) -> MemoryCompressResult:
        pass


class DisabledMemoryClient:
    def read(self, session_id: str) -> str:
        raise RuntimeError("memory disabled")

    def compress(self, session_id: str, messages_text: str) -> MemoryCompressResult:
        raise RuntimeError("memory disabled")


class HttpMemoryClient:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def read(self, session_id: str) -> str:
        encoded_session_id = quote(session_id, safe="")
        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
            response = client.get(f"/api/v1/memories/{encoded_session_id}")
            response.raise_for_status()
            payload = response.json()
        return str(payload.get("content_markdown", ""))

    def compress(self, session_id: str, messages_text: str) -> MemoryCompressResult:
        encoded_session_id = quote(session_id, safe="")
        with httpx.Client(base_url=self._base_url, timeout=self._timeout) as client:
            response = client.post(
                f"/api/v1/memories/{encoded_session_id}/compress",
                json={"messages_text": messages_text},
            )
            response.raise_for_status()
            payload = response.json()
        return MemoryCompressResult(
            content_markdown=str(payload.get("content_markdown", "")),
            added_markdown=str(payload.get("added_markdown", "")),
            added_count=int(payload.get("added_count", 0)),
        )
