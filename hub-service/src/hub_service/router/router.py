from fastapi import APIRouter, WebSocket

from ..services.connection_state import NapcatConnectionState
from ..services.napcat_ws import NapcatWsGateway
from .schemas import HealthResponse


def create_router(
    napcat_ws_gateway: NapcatWsGateway,
    napcat_connection_state: NapcatConnectionState,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @router.websocket("/onebot/v11/ws")
    async def onebot_v11_ws(websocket: WebSocket) -> None:
        """NapCat 反向 WebSocket — 事件入口 + 动作发送出口。"""
        await napcat_ws_gateway.handle_connection(websocket)

    return router
