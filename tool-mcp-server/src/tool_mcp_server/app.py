from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    log_info(logger, "tool_mcp.boot", mcp_base_url=settings.mcp.hub_base_url)

    app = FastAPI(
        title="tool-mcp-server",
        version="0.1.0",
        description="AICHAN adapter, file, media understanding, and memory tools.",
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.on_event("startup")
    async def startup() -> None:
        log_info(logger, "tool_mcp.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        log_info(logger, "tool_mcp.stopping")

    return app


app = create_app()
