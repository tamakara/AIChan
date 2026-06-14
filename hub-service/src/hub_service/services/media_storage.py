from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import httpx

from ..config import FileServiceSettings


@dataclass(frozen=True)
class StoredMedia:
    object_key: str
    name: str
    mime: str
    size: int
    sha256: str


class MediaNotFoundError(RuntimeError):
    pass


class MediaStorage:
    """hub 的文件适配层：只传业务上下文，不拥有物理存储。"""

    def __init__(self, settings: FileServiceSettings) -> None:
        self._base_url = settings.base_url.rstrip("/")
        self._timeout = settings.timeout_seconds

    async def store_segment(
        self,
        *,
        event: dict[str, Any],
        segment_type: str,
        segment_index: int,
        data: dict[str, Any],
    ) -> StoredMedia:
        payload = {
            "url": str(data["url"]),
            "name": _media_name(data=data, segment_type=segment_type, segment_index=segment_index),
            "kind": segment_type,
        }
        response = await self._request_json("POST", "/api/v1/files/from-url", json=payload)
        return _stored_media_from_payload(response)

    async def metadata(self, object_key: str) -> StoredMedia:
        try:
            response = await self._request_json("GET", f"/api/v1/files/{object_key}/metadata")
        except MediaNotFoundError:
            raise
        return _stored_media_from_payload(response)

    async def content(self, object_key: str) -> bytes:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(f"/api/v1/files/{object_key}/content")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise MediaNotFoundError(object_key) from exc
                raise RuntimeError(f"file-service content request failed: status={exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"file-service request failed: {exc}") from exc
        return response.content

    async def _request_json(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                response = await client.request(method, path, json=json)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise MediaNotFoundError(path) from exc
                raise RuntimeError(f"file-service request failed: status={exc.response.status_code}") from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"file-service request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("file-service returned non-json payload") from exc
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"file-service returned invalid payload: {payload}")
        return payload


def _stored_media_from_payload(payload: dict[str, Any]) -> StoredMedia:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("file-service returned invalid file payload")
    return StoredMedia(
        object_key=str(data["object_key"]),
        name=str(data["name"]),
        mime=str(data["mime"]),
        size=int(data["size"]),
        sha256=str(data["sha256"]),
    )


def _media_name(*, data: dict[str, Any], segment_type: str, segment_index: int) -> str:
    raw_name = data.get("name") or data.get("file")
    if raw_name:
        return PurePosixPath(str(raw_name)).name
    return f"{segment_type}-{segment_index}"
