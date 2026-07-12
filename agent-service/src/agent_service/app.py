from fastapi import FastAPI

from .services import (
    Agent,
    HttpMemoryClient,
    LlmClient,
    McpGateway,
    SessionRegistry,
    ThreadedMemoryCompressionScheduler,
    SkillClient,
    create_observability,
)
from .config import get_settings
from .router import create_router


def create_app() -> FastAPI:
    settings = get_settings()

    observability = create_observability(settings.agent.langfuse)

    llm_client = LlmClient(
        model_name=settings.agent.model,
        api_key=settings.agent.openai_api_key,
        base_url=settings.agent.openai_base_url,
        timeout=settings.agent.llm_timeout,
        max_retries=settings.agent.llm_max_retries,
    )

    mcp_gateway = McpGateway(
        sse_url=settings.agent.mcp_sse_url,
        auth_token=settings.agent.mcp_auth_token,
    )
    mcp_gateway.register_mcp_server()

    memory_client = HttpMemoryClient(
        base_url=settings.agent.memory_base_url,
        timeout=settings.agent.memory_timeout,
    )
    memory_compression_scheduler = ThreadedMemoryCompressionScheduler(
        memory_client=memory_client,
        max_workers=1,
    )
    skill_client = SkillClient(settings.agent.skill_base_url, settings.agent.skill_timeout)

    agent = Agent(
        llm_client=llm_client,
        mcp_gateway=mcp_gateway,
        max_turns=settings.agent.max_turns,
        max_retries=settings.agent.llm_max_retries,
        temperature=settings.agent.temperature,
        observability=observability,
        memory_client=memory_client,
        memory_compression_scheduler=memory_compression_scheduler,
        memory_enabled=settings.agent.memory_enabled,
        memory_compress_every_n_records=settings.agent.memory_compress_every_n_records,
        skill_client=skill_client,
    )

    session_registry = SessionRegistry(max_turns=settings.agent.max_turns)

    app = FastAPI(
        title="agent-service FastAPI service",
        version="0.1.0",
        description="HTTP API wrapper around Agent.",
    )
    app.include_router(
        create_router(
            agent=agent,
            session_registry=session_registry,
            skill_client=skill_client,
        )
    )

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        memory_compression_scheduler.shutdown(
            timeout_seconds=settings.agent.memory_timeout,
        )
        observability.flush(timeout_seconds=settings.agent.langfuse.request_timeout)

    return app


app = create_app()
