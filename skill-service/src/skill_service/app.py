from pathlib import Path

from fastapi import FastAPI, HTTPException, status

from .config import get_settings
from .registry import SkillRegistry
from .schemas import AdapterSkillSnapshot, HealthResponse, ResolveSkillsRequest, ResolveSkillsResponse


def create_app(registry: SkillRegistry | None = None) -> FastAPI:
    settings = get_settings()
    registry = registry or SkillRegistry(
        Path(settings.skills.system_root), settings.skills.max_skill_bytes,
        settings.skills.max_adapter_snapshot_bytes,
    )
    app = FastAPI(title="skill-service", version="0.1.0")

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse()

    @app.put("/api/v1/adapters/skills")
    def replace_adapter(snapshot: AdapterSkillSnapshot) -> dict[str, bool]:
        try:
            registry.replace_adapter(snapshot)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return {"updated": True}

    @app.delete("/api/v1/adapters/{adapter_id}/{instance_id}/skills")
    def deactivate_adapter(adapter_id: str, instance_id: str) -> dict[str, bool]:
        registry.deactivate_adapter(adapter_id, instance_id)
        return {"deactivated": True}

    @app.post("/api/v1/skills/resolve", response_model=ResolveSkillsResponse)
    def resolve(request: ResolveSkillsRequest) -> ResolveSkillsResponse:
        return ResolveSkillsResponse(skills=registry.resolve(request.adapter_id, request.instance_id))

    return app


app = create_app()
