import asyncio
from contextlib import suppress

from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router import create_router
from .services import FileStorage


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    cleanup_task: asyncio.Task[None] | None = None
    log_info(
        logger,
        "file_app.boot",
        bucket=settings.storage.bucket,
        database_path=settings.storage.database_path,
    )

    file_storage = FileStorage(settings.storage)

    app = FastAPI(
        title="file-service",
        version="0.1.0",
        description="AICHAN file storage service backed by MinIO SHA-256 objects and SQLite metadata.",
    )
    app.include_router(create_router(file_storage=file_storage))

    @app.on_event("startup")
    async def startup() -> None:
        nonlocal cleanup_task
        await file_storage.initialize()
        cleanup_task = asyncio.create_task(
            _run_expired_file_cleanup(
                file_storage=file_storage,
                interval_seconds=settings.storage.cleanup_interval_seconds,
                batch_size=settings.storage.cleanup_batch_size,
            )
        )
        log_info(logger, "file_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_started_at = start_timer()
        log_info(logger, "file_app.stopping")
        if cleanup_task is not None:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task
        log_info(logger, "file_app.stopped", elapsed_ms=elapsed_ms(shutdown_started_at))

    return app


app = create_app()


async def _run_expired_file_cleanup(
    *,
    file_storage: FileStorage,
    interval_seconds: float,
    batch_size: int,
) -> None:
    logger = get_logger("cleanup")
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            deleted_count = await file_storage.cleanup_expired_files(limit=batch_size)
        except Exception as exc:
            log_info(logger, "file_cleanup.failed", error=repr(exc))
            continue
        if deleted_count:
            log_info(logger, "file_cleanup.deleted", deleted_count=deleted_count)
