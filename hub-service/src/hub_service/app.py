from fastapi import FastAPI

from .config import get_settings
from .logger import elapsed_ms, get_logger, log_info, start_timer
from .router import create_router
from .services import EventConsumerWorker, HubRedisStream, OutboundClient, SessionRegistry


def create_app() -> FastAPI:
    boot_started_at = start_timer()
    logger = get_logger("app")
    settings = get_settings()
    log_info(
        logger,
        "hub_app.boot",
        events_stream=settings.redis.events_stream,
        events_group=settings.redis.events_group,
        actions_stream=settings.redis.actions_stream,
    )

    redis_stream = HubRedisStream(settings.redis)
    outbound_client = OutboundClient(
        agent_service_url=settings.hub.agent_url,
        redis_stream=redis_stream,
    )
    session_registry = SessionRegistry(
        outbound_client=outbound_client,
        debounce_seconds=settings.hub.debounce_seconds,
        post_run_grace_seconds=settings.hub.post_run_grace_seconds,
        max_wait_seconds=settings.hub.max_wait_seconds,
    )
    event_consumer = EventConsumerWorker(
        redis_stream=redis_stream,
        session_registry=session_registry,
    )

    app = FastAPI(
        title="hub-service",
        version="0.1.0",
        description="QQ reminder hub driven by Redis streams.",
    )

    app.include_router(create_router())

    @app.on_event("startup")
    async def startup() -> None:
        await redis_stream.startup()
        await event_consumer.start()
        log_info(logger, "hub_app.ready", elapsed_ms=elapsed_ms(boot_started_at))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        shutdown_started_at = start_timer()
        log_info(logger, "hub_app.stopping")
        await event_consumer.stop()
        await session_registry.shutdown()
        await outbound_client.aclose()
        await redis_stream.shutdown()
        log_info(logger, "hub_app.stopped", elapsed_ms=elapsed_ms(shutdown_started_at))

    return app


app = create_app()
