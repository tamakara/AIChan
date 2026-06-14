from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import mimetypes
from pathlib import Path, PurePosixPath
import sqlite3
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
NOT_FOUND_CODES = {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}


@dataclass(frozen=True)
class FileRecord:
    object_key: str
    name: str
    mime: str
    size: int
    sha256: str


class FileNotFoundError(RuntimeError):
    pass


class UnsupportedTextFileError(RuntimeError):
    pass


class FileStorage:
    """文件存储边界：MinIO 只存 SHA 真身，SQLite 保存可变业务影子。"""

    def __init__(self, settings: StorageSettings) -> None:
        self._settings = settings
        self._client = Minio(
            endpoint=settings.endpoint,
            access_key=settings.access_key,
            secret_key=settings.secret_key,
            secure=settings.secure,
        )
        self._database_path = Path(settings.database_path)

    async def initialize(self) -> None:
        exists = await asyncio.to_thread(self._client.bucket_exists, self._settings.bucket)
        if not exists:
            await asyncio.to_thread(self._client.make_bucket, self._settings.bucket)
        await asyncio.to_thread(self._initialize_database)

    async def store_url(self, *, url: str, name: str | None, mime: str | None, kind: str | None) -> FileRecord:
        content, response_mime = await self._download(url)
        display_name = _file_name(name=name, url=url, kind=kind)
        resolved_mime = _file_mime(name=display_name, url=url, explicit_mime=mime, response_mime=response_mime, kind=kind)
        return await self.store_bytes(content=content, name=display_name, mime=resolved_mime)

    async def store_bytes(self, *, content: bytes, name: str, mime: str) -> FileRecord:
        if len(content) > self._settings.max_object_bytes:
            raise ValueError("file object is too large")
        digest = sha256(content).hexdigest()
        record = FileRecord(
            object_key=digest,
            name=PurePosixPath(name).name or "file",
            mime=mime,
            size=len(content),
            sha256=digest,
        )
        await asyncio.to_thread(self._put_object_if_absent, record, content)
        await asyncio.to_thread(self._upsert_metadata, record)
        return record

    async def metadata(self, object_key: str) -> FileRecord:
        _validate_object_key(object_key)
        row = await asyncio.to_thread(self._get_metadata_row, object_key)
        if row is None:
            raise FileNotFoundError(object_key)
        name, mime, size = row
        return FileRecord(object_key=object_key, name=name, mime=mime, size=size, sha256=object_key)

    async def content(self, object_key: str) -> bytes:
        _validate_object_key(object_key)

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
            if exc.code in NOT_FOUND_CODES:
                raise FileNotFoundError(object_key) from exc
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
            raise ValueError("file object is too large")
        return content, response.headers.get("content-type")

    def _initialize_database(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS physical_files (
                    sha256 TEXT PRIMARY KEY,
                    mime TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS file_shadows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL,
                    name TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (sha256) REFERENCES physical_files(sha256)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_file_shadows_sha256_id ON file_shadows(sha256, id)")

    def _put_object_if_absent(self, record: FileRecord, content: bytes) -> None:
        try:
            self._client.stat_object(self._settings.bucket, record.object_key)
            return
        except S3Error as exc:
            if exc.code not in NOT_FOUND_CODES:
                raise

        # object_key 固定为 SHA-256，因此物理层天然幂等；重复内容只会增加 SQLite 影子。
        self._client.put_object(
            bucket_name=self._settings.bucket,
            object_name=record.object_key,
            data=BytesIO(content),
            length=len(content),
            content_type=record.mime,
            metadata={"sha256": record.sha256, "size": str(record.size)},
        )

    def _upsert_metadata(self, record: FileRecord) -> None:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO physical_files (sha256, mime, size, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    mime=excluded.mime,
                    size=excluded.size,
                    updated_at=excluded.updated_at
                """,
                (record.sha256, record.mime, record.size, now, now),
            )
            # 同一个真身可能被不同业务场景以不同名字看到；这里不覆盖历史影子，
            # 读取 metadata 时取最新影子作为展示名，避免把来源维度写回 object_key。
            conn.execute(
                """
                INSERT INTO file_shadows (sha256, name, mime, size, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record.sha256, record.name, record.mime, record.size, now),
            )

    def _get_metadata_row(self, object_key: str) -> tuple[str, str, int] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COALESCE(s.name, 'file') AS name,
                    COALESCE(s.mime, f.mime) AS mime,
                    f.size AS size
                FROM physical_files AS f
                LEFT JOIN file_shadows AS s
                    ON s.id = (
                        SELECT id FROM file_shadows
                        WHERE sha256 = f.sha256
                        ORDER BY id DESC
                        LIMIT 1
                    )
                WHERE f.sha256 = ?
                """,
                (object_key,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), int(row[2])

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _file_name(*, name: str | None, url: str, kind: str | None) -> str:
    if name:
        return PurePosixPath(str(name)).name
    parsed_name = PurePosixPath(unquote(urlparse(url).path)).name
    if parsed_name:
        return parsed_name
    return f"{kind or 'file'}"


def _file_mime(
    *,
    name: str,
    url: str,
    explicit_mime: str | None,
    response_mime: str | None,
    kind: str | None,
) -> str:
    normalized_explicit_mime = _normalize_mime(explicit_mime)
    if normalized_explicit_mime and normalized_explicit_mime not in GENERIC_MIME_TYPES:
        return normalized_explicit_mime

    normalized_response_mime = _normalize_mime(response_mime)
    if normalized_response_mime and normalized_response_mime not in GENERIC_MIME_TYPES:
        return normalized_response_mime

    # NapCat 临时地址经常只有 application/octet-stream，只能用文件名/URL/段类型补足 MIME。
    guessed, _ = mimetypes.guess_type(name)
    if guessed is None:
        guessed, _ = mimetypes.guess_type(urlparse(url).path)
    if guessed is not None:
        return guessed
    if kind == "video":
        return "video/mp4"
    return normalized_explicit_mime or normalized_response_mime or "application/octet-stream"


def _normalize_mime(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _is_text_like(record: FileRecord) -> bool:
    if record.mime.startswith("text/"):
        return True
    return PurePosixPath(record.name).suffix.lower() in TEXT_EXTENSIONS


def _validate_object_key(object_key: str) -> None:
    if len(object_key) != 64 or any(char not in "0123456789abcdef" for char in object_key):
        raise FileNotFoundError(object_key)


def _now() -> str:
    return datetime.now(UTC).isoformat()
