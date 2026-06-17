from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router import create_router
from .services import MemoryService, OpenAiMemoryCompressor


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()

    log_info(logger, "memory_app.boot", root_dir=settings.memory.root_dir)

    memory_service = MemoryService(
        root_dir=settings.memory.root_dir,
        compressor=OpenAiMemoryCompressor(settings.memory),
    )

    app = FastAPI(
        title="memory-service",
        version="0.1.0",
        description="AICHAN per-session markdown memory service.",
    )
    app.include_router(create_router(memory_service=memory_service))

    @app.on_event("startup")
    async def startup() -> None:
        log_info(logger, "memory_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    return app


app = create_app()
