from fastapi import FastAPI

from .config import get_settings
from .router.router import create_router
from .services import AdapterRegistry, AgentClient, FileServiceClient, SessionRegistry, SkillServiceClient


def create_app() -> FastAPI:
    settings = get_settings()
    agent = AgentClient(settings.hub.agent_url)
    files = FileServiceClient(settings.hub.file_service_url)
    skills = SkillServiceClient(settings.hub.skill_service_url)
    adapters = AdapterRegistry(
        settings.hub.adapter_tokens, skills, settings.hub.ack_timeout_seconds,
        settings.hub.ack_max_attempts, settings.hub.capability_timeout_seconds,
    )
    sessions = SessionRegistry(agent, adapters, settings.hub.debounce_seconds)
    adapters.set_event_handler(sessions.submit_event)

    app = FastAPI(title="hub-service", version="1.0.0", description="AICHAN channel-neutral adapter hub")
    app.include_router(create_router(adapters, sessions, files))

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await sessions.shutdown()
        await agent.aclose()
        await files.aclose()
        await skills.aclose()

    return app


app = create_app()
