from fastapi import FastAPI

from .services import Agent, LlmClient, McpGateway, SessionRegistry, create_observability
from .config import get_settings
from .logger import get_logger, log_info
from .router import create_router


def create_app() -> FastAPI:
    logger = get_logger("app")
    settings = get_settings()

    log_info(
        logger,
        "agent_app.boot",
        model=settings.agent.model,
        max_turns=settings.agent.max_turns,
        mcp_sse_url=settings.agent.mcp_sse_url,
    )
    observability = create_observability(settings.agent.langfuse)

    llm_client = LlmClient(
        model_name=settings.agent.model,
        api_key=settings.agent.openai_api_key,
        base_url=settings.agent.openai_base_url,
        observability=observability,
    )

    mcp_gateway = McpGateway(
        sse_url=settings.agent.mcp_sse_url,
        auth_token=settings.agent.mcp_auth_token,
        observability=observability,
    )
    mcp_gateway.register_mcp_server()

    agent = Agent(
        llm_client=llm_client,
        mcp_gateway=mcp_gateway,
        max_turns=settings.agent.max_turns,
        temperature=settings.agent.temperature,
        observability=observability,
    )

    session_registry = SessionRegistry()

    app = FastAPI(
        title="agent-service FastAPI service",
        version="0.1.0",
        description="HTTP API wrapper around Agent.",
    )
    app.include_router(
        create_router(
            agent=agent,
            session_registry=session_registry,
        )
    )

    @app.on_event("startup")
    async def on_startup() -> None:
        # ready 日志放在 startup 事件中，确保只在服务进入可接流量阶段后输出。
        log_info(logger, "agent_app.ready")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        observability.flush(timeout_seconds=settings.agent.langfuse.request_timeout)

    return app


app = create_app()
