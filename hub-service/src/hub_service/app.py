from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router import create_router
from .services import NapcatConnectionState, NapcatWsGateway, OutboundClient, SessionRegistry


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    log_info(
        logger,
        "hub_app.boot",
        agent_url=settings.hub.agent_url,
        allowed_user_ids=list(settings.hub.allowed_user_ids),
    )

    # WS 连接状态与网关
    napcat_connection_state = NapcatConnectionState()
    napcat_ws_gateway = NapcatWsGateway(
        connection_state=napcat_connection_state,
        action_timeout_seconds=settings.napcat.ws_action_timeout_seconds,
        allowed_user_ids=set(settings.hub.allowed_user_ids),
    )

    # 下游通信与会话管理
    outbound_client = OutboundClient(
        agent_service_url=settings.hub.agent_url,
        napcat_ws=napcat_ws_gateway,
    )
    session_registry = SessionRegistry(
        outbound_client=outbound_client,
        debounce_seconds=settings.hub.debounce_seconds,
    )

    # WS 事件回调 → 会话注册中心
    napcat_ws_gateway.set_on_event(session_registry.submit_event)

    app = FastAPI(
        title="hub-service",
        version="0.1.0",
        description="QQ session hub — OneBot v11 native, no Redis.",
    )

    app.include_router(
        create_router(
            napcat_ws_gateway=napcat_ws_gateway,
            napcat_connection_state=napcat_connection_state,
        )
    )

    @app.on_event("startup")
    async def startup() -> None:
        log_info(logger, "hub_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_started_at = start_timer()
        log_info(logger, "hub_app.stopping")
        await session_registry.shutdown()
        await outbound_client.aclose()
        log_info(logger, "hub_app.stopped", elapsed_ms=elapsed_ms(shutdown_started_at))

    return app


app = create_app()
