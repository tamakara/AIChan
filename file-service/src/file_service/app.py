from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router import create_router
from .services import FileStorage


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
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
        await file_storage.initialize()
        log_info(logger, "file_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_started_at = start_timer()
        log_info(logger, "file_app.stopping")
        log_info(logger, "file_app.stopped", elapsed_ms=elapsed_ms(shutdown_started_at))

    return app


app = create_app()
