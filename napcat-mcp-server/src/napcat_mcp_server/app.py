from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router.router import create_router
from .services.connection_state import NapcatConnectionState
from .services.napcat_ws import NapcatWsGateway


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    log_info(logger, "napcat_mcp.boot")

    napcat_connection_state = NapcatConnectionState()
    napcat_ws_gateway = NapcatWsGateway(
        action_timeout_seconds=settings.napcat.ws_action_timeout_seconds,
    )

    app = FastAPI(
        title="napcat-mcp-server",
        version="0.1.0",
        description="NapCat MCP server — exposes OneBot v11 tools via MCP.",
    )

    app.include_router(
        create_router(
            napcat_ws_gateway=napcat_ws_gateway,
            napcat_connection_state=napcat_connection_state,
        )
    )

    @app.on_event("startup")
    async def startup() -> None:
        log_info(logger, "napcat_mcp.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        log_info(logger, "napcat_mcp.stopping")

    return app


app = create_app()
