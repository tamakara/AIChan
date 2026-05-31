from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from ..services.connection_state import NapcatConnectionState
from ..services.napcat_ws import NapcatWsGateway
from .schemas import (
    HealthResponse,
    MessageHistoryData,
    MessageHistoryResponse,
    UserInfoResponse,
)


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
        napcat_connection_state.set(websocket)
        try:
            await napcat_ws_gateway.handle_connection(websocket)
        except WebSocketDisconnect:
            pass
        finally:
            napcat_connection_state.clear(websocket)

    @router.get("/api/v1/user/{user_id}/info", response_model=UserInfoResponse)
    async def get_user_info(user_id: int) -> UserInfoResponse:
        websocket = napcat_connection_state.get()
        if websocket is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="napcat reverse ws is not connected",
            )

        try:
            result = await napcat_ws_gateway.send_action(
                websocket=websocket,
                action="get_stranger_info",
                params={"user_id": user_id, "no_cache": True},
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="napcat action timeout",
            ) from exc

        return UserInfoResponse(ok=True, data=result)

    @router.get("/api/v1/message/history", response_model=MessageHistoryResponse)
    async def get_message_history(
        message_type: str = Query(min_length=1, pattern="^(group|private)$"),
        peer_id: int = Query(ge=1),
        limit: int = Query(default=20, ge=1, le=50),
        before_message_id: int | None = Query(default=None, ge=1),
    ) -> MessageHistoryResponse:
        websocket = napcat_connection_state.get()
        if websocket is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="napcat reverse ws is not connected",
            )

        message_seq = before_message_id if before_message_id is not None else 0

        if message_type == "group":
            action = "get_group_msg_history"
            params: dict = {"group_id": peer_id, "count": limit, "message_seq": message_seq}
        else:
            action = "get_friend_msg_history"
            params = {"user_id": peer_id, "count": limit, "message_seq": message_seq}

        try:
            result = await napcat_ws_gateway.send_action(
                websocket=websocket,
                action=action,
                params=params,
            )
            data = _normalize_history_result(result)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="napcat action timeout",
            ) from exc

        return MessageHistoryResponse(ok=True, data=data)

    return router


def _normalize_history_result(raw_result: dict) -> MessageHistoryData:
    if not isinstance(raw_result, dict):
        raise ValueError("history response must be a dict")

    payload = raw_result.get("data")
    if not isinstance(payload, dict):
        raise ValueError("history response data must be a dict")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("history response messages must be a list")

    messages = [m for m in raw_messages if isinstance(m, dict)]
    next_before_message_id = _extract_next_before_message_id(messages)

    return MessageHistoryData(
        messages=messages,
        next_before_message_id=next_before_message_id,
    )


def _extract_next_before_message_id(messages: list[dict]) -> int | None:
    for message in reversed(messages):
        message_id = message.get("message_id")
        if message_id is None:
            continue
        try:
            return int(message_id)
        except (TypeError, ValueError):
            continue
    return None
