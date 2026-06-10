from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import mimetypes
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from minio import Minio
from minio.error import S3Error

from ..config import StorageSettings

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
}
GENERIC_MIME_TYPES = {"application/octet-stream", "binary/octet-stream", "application/x-octet-stream"}


@dataclass(frozen=True)
class StoredMedia:
    object_key: str
    name: str
    mime: str
    size: int
    sha256: str


class MediaNotFoundError(RuntimeError):
    pass


class UnsupportedTextFileError(RuntimeError):
    pass


class MediaStorage:
    """媒体存储边界：hub 负责拿原始 URL，agent/MCP 只看稳定 object_key。"""

    def __init__(self, settings: StorageSettings) -> None:
        self._settings = settings
        self._client = Minio(
            endpoint=settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )

    async def ensure_bucket(self) -> None:
        exists = await asyncio.to_thread(self._client.bucket_exists, self._settings.bucket)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, self._settings.bucket)

    async def store_segment(
        self,
        *,
        event: dict[str, Any],
        segment_type: str,
        segment_index: int,
        data: dict[str, Any],
    ) -> StoredMedia:
        url = str(data["url"])
        content, response_mime = await self._download(url)
        digest = sha256(content).hexdigest()
        name = _media_name(data=data, url=url, segment_type=segment_type, segment_index=segment_index)
        mime = _media_mime(name=name, url=url, response_mime=response_mime, segment_type=segment_type)
        extension = _media_extension(name=name, mime=mime)
        object_key = (
            f"qq/private/{event.get('user_id')}/{event.get('message_id')}/"
            f"{segment_index}-{digest}{extension}"
        )
        stored = StoredMedia(
            object_key=object_key,
            name=name,
            mime=mime,
            size=len(content),
            sha256=digest,
        )
        await asyncio.to_thread(self._put_object, stored, content)
        return stored

    async def metadata(self, object_key: str) -> StoredMedia:
        try:
            stat = await asyncio.to_thread(self._client.stat_object, self._settings.bucket, object_key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                raise MediaNotFoundError(object_key) from exc
            raise

        metadata = {key.lower(): value for key, value in (stat.metadata or {}).items()}
        name = metadata.get("x-amz-meta-name") or metadata.get("name") or PurePosixPath(object_key).name
        mime = metadata.get("x-amz-meta-mime") or metadata.get("mime") or stat.content_type or "application/octet-stream"
        digest = metadata.get("x-amz-meta-sha256") or metadata.get("sha256") or ""
        size = int(metadata.get("x-amz-meta-size") or metadata.get("size") or stat.size or 0)
        return StoredMedia(object_key=object_key, name=name, mime=mime, size=size, sha256=digest)

    async def content(self, object_key: str) -> bytes:
        def read_object() -> bytes:
            response = self._client.get_object(self._settings.bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(read_object)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                raise MediaNotFoundError(object_key) from exc
            raise

    async def text(self, object_key: str, max_chars: int) -> tuple[str, bool]:
        metadata = await self.metadata(object_key)
        if not _is_text_like(metadata):
            raise UnsupportedTextFileError(object_key)
        content = await self.content(object_key)
        text = content.decode("utf-8", errors="replace")
        if len(text) <= max_chars:
            return text, False
        return text[:max_chars], True

    async def _download(self, url: str) -> tuple[bytes, str | None]:
        async with httpx.AsyncClient(timeout=self._settings.download_timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        content = response.content
        if len(content) > self._settings.max_object_bytes:
            raise ValueError("media object is too large")
        return content, response.headers.get("content-type")

    def _put_object(self, stored: StoredMedia, content: bytes) -> None:
        # MinIO 用户元数据会在 stat_object 中返回，用于后续 API 不依赖 object_key 反推文件属性。
        self._client.put_object(
            bucket_name=self._settings.bucket,
            object_name=stored.object_key,
            data=BytesIO(content),
            length=len(content),
            content_type=stored.mime,
            metadata={
                "name": stored.name,
                "mime": stored.mime,
                "size": str(stored.size),
                "sha256": stored.sha256,
            },
        )


def _media_name(
    *,
    data: dict[str, Any],
    url: str,
    segment_type: str,
    segment_index: int,
) -> str:
    raw_name = data.get("name") or data.get("file")
    if raw_name:
        return PurePosixPath(str(raw_name)).name

    parsed_name = PurePosixPath(unquote(urlparse(url).path)).name
    if parsed_name:
        return parsed_name
    return f"{segment_type}-{segment_index}"


def _media_mime(*, name: str, url: str, response_mime: str | None, segment_type: str) -> str:
    normalized_response_mime = ""
    if response_mime:
        normalized_response_mime = response_mime.split(";", 1)[0].strip().lower()
        if normalized_response_mime and normalized_response_mime not in GENERIC_MIME_TYPES:
            return normalized_response_mime

    # NapCat 的临时下载地址有时只返回 application/octet-stream。此时优先相信文件名/URL
    # 后缀和 OneBot 段类型，否则视频会被存成普通二进制，后续 MCP 工具无法识别。
    guessed, _ = mimetypes.guess_type(name)
    if guessed is None:
        guessed, _ = mimetypes.guess_type(urlparse(url).path)
    if guessed is not None:
        return guessed
    if segment_type == "video":
        return "video/mp4"
    return normalized_response_mime or "application/octet-stream"


def _media_extension(*, name: str, mime: str) -> str:
    suffix = PurePosixPath(name).suffix
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(mime)
    return guessed or ".bin"


def _is_text_like(media: StoredMedia) -> bool:
    if media.mime.startswith("text/"):
        return True
    return PurePosixPath(media.name).suffix.lower() in TEXT_EXTENSIONS
