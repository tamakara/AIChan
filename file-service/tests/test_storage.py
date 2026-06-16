from hashlib import sha256
from datetime import UTC, datetime, timedelta

import pytest

from file_service.config import StorageSettings
from file_service.services import storage as storage_module
from file_service.services.storage import FileNotFoundError, FileStorage, _file_mime


class StubMinio:
    def __init__(self, *args, **kwargs) -> None:
        self.objects: dict[str, bytes] = {}
        self.removed_objects: list[str] = []

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def make_bucket(self, bucket: str) -> None:
        return

    def stat_object(self, bucket: str, object_name: str):
        if object_name not in self.objects:
            raise StubS3Error("NoSuchKey")
        return object()

    def put_object(self, bucket_name, object_name, data, length, content_type, metadata):
        self.objects[object_name] = data.read()

    def remove_object(self, bucket, object_name):
        if object_name not in self.objects:
            raise StubS3Error("NoSuchKey")
        self.removed_objects.append(object_name)
        del self.objects[object_name]


class StubS3Error(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@pytest.fixture(autouse=True)
def patch_minio(monkeypatch) -> None:
    monkeypatch.setattr(storage_module, "S3Error", StubS3Error)
    monkeypatch.setattr(storage_module, "Minio", StubMinio)


@pytest.mark.asyncio
async def test_store_bytes_uses_sha256_object_key_and_keeps_latest_shadow(tmp_path) -> None:
    service = FileStorage(_settings(tmp_path))
    await service.initialize()

    first = await service.store_bytes(content=b"hello", name="first.txt", mime="text/plain")
    second = await service.store_bytes(content=b"hello", name="second.txt", mime="text/plain")
    metadata = await service.metadata(first.object_key)

    assert first.object_key == sha256(b"hello").hexdigest()
    assert second.object_key == first.object_key
    assert metadata.name == "second.txt"


@pytest.mark.asyncio
async def test_metadata_hides_expired_file(tmp_path) -> None:
    service = FileStorage(_settings(tmp_path))
    await service.initialize()

    record = await service.store_bytes(content=b"hello", name="old.txt", mime="text/plain")
    expired_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()

    with service._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE physical_files SET updated_at = ? WHERE sha256 = ?",
            (expired_at, record.sha256),
        )

    with pytest.raises(FileNotFoundError):
        await service.metadata(record.object_key)


@pytest.mark.asyncio
async def test_cleanup_expired_files_deletes_metadata_and_object(tmp_path) -> None:
    service = FileStorage(_settings(tmp_path))
    await service.initialize()

    record = await service.store_bytes(content=b"hello", name="old.txt", mime="text/plain")
    expired_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()

    with service._connect() as conn:  # noqa: SLF001
        conn.execute(
            "UPDATE physical_files SET updated_at = ? WHERE sha256 = ?",
            (expired_at, record.sha256),
        )

    deleted_count = await service.cleanup_expired_files(limit=10)

    assert deleted_count == 1
    assert record.object_key not in service._client.objects  # noqa: SLF001
    with pytest.raises(FileNotFoundError):
        await service.metadata(record.object_key)


def test_file_mime_prefers_video_extension_over_generic_response_mime() -> None:
    mime = _file_mime(
        name="clip.mp4",
        url="https://example.test/download",
        explicit_mime=None,
        response_mime="application/octet-stream",
        kind="video",
    )

    assert mime == "video/mp4"


def _settings(tmp_path) -> StorageSettings:
    return StorageSettings(
        endpoint="minio:9000",
        bucket="files",
        access_key="minio_user",
        secret_key="minio_password",
        secure=False,
        database_path=str(tmp_path / "files.sqlite3"),
        download_timeout_seconds=5,
        max_object_bytes=1024,
        expire_after_seconds=604800,
        cleanup_interval_seconds=3600,
        cleanup_batch_size=100,
    )
