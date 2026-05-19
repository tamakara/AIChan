from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from ..services.adapter_service import AdapterService
from ..services.connection_state import NapcatConnectionState
from ..services.napcat_ws_gateway import NapcatWsGateway
from .schemas import (
    HealthResponse,
    MessageHistoryResponse,
    UserInfoResponse,
)


def create_router(
    adapter_service: AdapterService,
    napcat_ws_gateway: NapcatWsGateway,
    napcat_connection_state: NapcatConnectionState,
) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @router.websocket("/onebot/v11/ws")
    async def onebot_v11_ws(websocket: WebSocket) -> None:
        napcat_connection_state.set(websocket)
        try:
            await napcat_ws_gateway.handle_connection(websocket)
        except WebSocketDisconnect:
            pass
        finally:
            napcat_connection_state.clear(websocket)

    @router.get("/api/v1/user/{user_id}/info", response_model=UserInfoResponse)
    async def get_user_info(user_id: str) -> UserInfoResponse:
        websocket = napcat_connection_state.get()
        if websocket is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="onebot reverse ws is not connected",
            )

        try:
            outbound_action = adapter_service.build_get_user_info_action(abstract_user_id=user_id)
            result = await napcat_ws_gateway.send_action(
                websocket=websocket,
                action=outbound_action.action,
                params=outbound_action.params,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="onebot reverse ws action timeout",
            ) from exc

        return UserInfoResponse(ok=True, data=result)

    @router.get("/api/v1/message/history", response_model=MessageHistoryResponse)
    async def get_message_history(
        session_id: str = Query(min_length=1),
        limit: int = Query(default=20, ge=1, le=50),
        before_message_id: int | None = Query(default=None, ge=1),
    ) -> MessageHistoryResponse:
        websocket = napcat_connection_state.get()
        if websocket is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="onebot reverse ws is not connected",
            )

        try:
            outbound_action = adapter_service.build_get_history_action(
                session_id=session_id,
                limit=limit,
                before_message_id=before_message_id,
            )
            result = await napcat_ws_gateway.send_action(
                websocket=websocket,
                action=outbound_action.action,
                params=outbound_action.params,
            )
            data = adapter_service.normalize_history_result(session_id=session_id, raw_result=result)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="onebot reverse ws action timeout",
            ) from exc

        return MessageHistoryResponse(ok=True, data=data)

    return router

