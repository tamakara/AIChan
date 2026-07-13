from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..adapters.registry import AdapterRegistry
from .schemas import HealthResponse


def create_router(*, adapters: AdapterRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.get("/readyz", response_model=HealthResponse)
    async def readyz() -> HealthResponse:
        return HealthResponse(status="ready")

    @router.websocket("/api/v2/adapters/ws")
    async def adapter_ws(websocket: WebSocket) -> None:
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not adapters.token_allowed(token):
            await websocket.close(code=4401, reason="unauthorized")
            return
        try:
            await adapters.handle(websocket, token)
        except (WebSocketDisconnect, RuntimeError):
            return
        except (ValueError, PermissionError) as exc:
            await websocket.close(code=4400, reason=str(exc))

    @router.get("/api/v2/adapters")
    async def list_adapters() -> dict[str, object]:
        return {"adapters": adapters.status()}

    return router
