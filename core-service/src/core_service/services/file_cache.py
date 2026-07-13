from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass
from email.message import Message
from pathlib import Path, PurePath
from urllib.parse import quote
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class CachedFile:
    file_ref: str
    path: Path
    name: str
    mime_type: str
    size: int


class FileCache:
    """Adapter 文件的短期缓存；Adapter 始终是权威来源，缓存可随时丢弃。"""

    def __init__(self, *, root_dir: Path, ttl_seconds: int, cleanup_interval_seconds: int, max_file_bytes: int, timeout_seconds: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        self._root = root_dir
        self._ttl = ttl_seconds
        self._cleanup_interval = cleanup_interval_seconds
        self._max_bytes = max_file_bytes
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True)
        self._entries: dict[str, CachedFile] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._state_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        await self.cleanup()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def get(self, *, adapter_key: tuple[str, str], file_ref: str, base_url: str, token: str) -> CachedFile:
        cache_key = _cache_key(adapter_key, file_ref)
        async with self._state_lock:
            lock = self._locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._entries.get(cache_key)
            if cached is not None and cached.path.exists() and not _expired(cached.path, self._ttl):
                os.utime(cached.path, None)
                return cached
            entry = await self._download(cache_key=cache_key, file_ref=file_ref, base_url=base_url, token=token)
            self._entries[cache_key] = entry
            return entry

    async def cleanup(self) -> None:
        if not self._root.exists():
            return
        cutoff = time.time() - self._ttl
        for path in self._root.iterdir():
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        live_paths = {entry.path for entry in self._entries.values() if entry.path.exists()}
        self._entries = {key: entry for key, entry in self._entries.items() if entry.path in live_paths}

    async def close(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            await asyncio.gather(self._cleanup_task, return_exceptions=True)
        await self._client.aclose()

    async def _download(self, *, cache_key: str, file_ref: str, base_url: str, token: str) -> CachedFile:
        destination = self._root / cache_key
        temporary = self._root / f".{cache_key}.{uuid4().hex}.tmp"
        size = 0
        try:
            async with self._client.stream(
                "GET",
                f"{base_url.rstrip('/')}/{quote(file_ref, safe='')}",
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self._max_bytes:
                    raise ValueError("Adapter 文件超过大小限制")
                with temporary.open("wb") as target:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_bytes:
                            raise ValueError("Adapter 文件超过大小限制")
                        target.write(chunk)
                temporary.replace(destination)
                return CachedFile(
                    file_ref=file_ref,
                    path=destination,
                    name=_response_name(response.headers.get("content-disposition"), file_ref),
                    mime_type=response.headers.get("content-type", "application/octet-stream").split(";", 1)[0].strip().lower(),
                    size=size,
                )
        finally:
            temporary.unlink(missing_ok=True)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self._cleanup_interval)
            try:
                await self.cleanup()
            except Exception:
                # 清理只是缓存维护，失败不能影响消息与感知主流程。
                continue


def _cache_key(adapter_key: tuple[str, str], file_ref: str) -> str:
    raw = f"{adapter_key[0]}\0{adapter_key[1]}\0{file_ref}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _expired(path: Path, ttl_seconds: int) -> bool:
    return path.stat().st_mtime < time.time() - ttl_seconds


def _response_name(content_disposition: str | None, file_ref: str) -> str:
    if content_disposition:
        message = Message()
        message["content-disposition"] = content_disposition
        filename = message.get_filename()
        if filename:
            return PurePath(filename).name
    fallback = PurePath(file_ref).name
    return fallback or "file"
