from __future__ import annotations

from base64 import b64encode
from typing import Any

import httpx


class HubMediaClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=30,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def store_url(self, url: str, name: str | None, mime_type: str | None, kind: str) -> dict[str, Any]:
        response = await self._client.post("/api/v1/adapter/files/from-url", json={
            "url": url, "name": name, "mime_type": mime_type, "kind": kind,
        })
        response.raise_for_status()
        return dict(response.json()["data"])

    async def metadata(self, object_key: str) -> dict[str, Any]:
        response = await self._client.get(f"/api/v1/adapter/files/{object_key}/metadata")
        response.raise_for_status()
        return dict(response.json()["data"])

    async def base64_file(self, object_key: str) -> str:
        response = await self._client.get(f"/api/v1/adapter/files/{object_key}/content")
        response.raise_for_status()
        return "base64://" + b64encode(response.content).decode("ascii")

    async def aclose(self) -> None:
        await self._client.aclose()
