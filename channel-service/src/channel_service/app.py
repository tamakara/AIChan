from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router.router import create_router
from .services.action_consumer import ActionConsumerWorker
from .services.channel_service import AdapterService
from .services.connection_state import NapcatConnectionState
from .services.napcat_ws_gateway import NapcatWsGateway
from .services.redis_stream import AdapterRedisStream


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    log_info(
        logger,
        "channel_app.boot",
        events_stream=settings.redis.events_stream,
        actions_stream=settings.redis.actions_stream,
        actions_group=settings.redis.actions_group,
    )

    redis_stream = AdapterRedisStream(settings.redis)
    channel_service = AdapterService()
    napcat_connection_state = NapcatConnectionState()
    napcat_ws_gateway = NapcatWsGateway(
        channel_service=channel_service,
        redis_stream=redis_stream,
        action_timeout_seconds=settings.adapter.onebot_ws_action_timeout_seconds,
    )
    action_consumer = ActionConsumerWorker(
        redis_stream=redis_stream,
        napcat_gateway=napcat_ws_gateway,
        napcat_connection_state=napcat_connection_state,
        channel_service=channel_service,
    )

    app = FastAPI(
        title="channel-service",
        version="0.1.0",
        description="Redis-stream OneBot adapter for reverse websocket and hub module.",
    )

    app.include_router(
        create_router(
            channel_service=channel_service,
            napcat_ws_gateway=napcat_ws_gateway,
            napcat_connection_state=napcat_connection_state,
        )
    )

    @app.on_event("startup")
    async def startup() -> None:
        await redis_stream.startup()
        await action_consumer.start()
        log_info(logger, "channel_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_started_at = start_timer()
        log_info(logger, "channel_app.stopping")
        await action_consumer.stop()
        await redis_stream.shutdown()
        log_info(logger, "channel_app.stopped", elapsed_ms=elapsed_ms(shutdown_started_at))

    return app


app = create_app()
