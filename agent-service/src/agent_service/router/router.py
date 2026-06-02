from fastapi import APIRouter, HTTPException

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..services import Agent, SessionRegistry
from ..services.session import SessionPreempted
from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    HealthResponse,
)


def create_router(
    agent: Agent,
    session_registry: SessionRegistry,
) -> APIRouter:
    router = APIRouter()
    logger = get_logger("router")

    @router.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.post("/sessions", response_model=CreateSessionResponse)
    def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
        session = session_registry.create(metadata=req.metadata)
        log_info(
            logger,
            "agent.session_created",
            agent_id=session.session_id,
        )
        return CreateSessionResponse(
            session_id=session.session_id,
            metadata=session.metadata,
        )

    @router.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict:
        deleted = session_registry.delete(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="session not found")
        log_info(
            logger,
            "agent.session_deleted",
            agent_id=session_id,
        )
        return {"deleted": True}

    @router.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        request_started_at = start_timer()
        session = session_registry.get(req.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        log_info(
            logger,
            "agent.chat_received",
            agent_id=req.session_id,
            message_len=len(req.batch),
        )

        try:
            reply_message = agent.run(
                session=session,
                user_message=req.batch,
            )
            log_info(
                logger,
                "agent.chat_completed",
                agent_id=req.session_id,
                reply_len=len(str(reply_message)),
                elapsed_ms=elapsed_ms(request_started_at),
            )
        except SessionPreempted as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            log_exception(
                logger,
                "agent.chat_failed",
                agent_id=req.session_id,
                elapsed_ms=elapsed_ms(request_started_at),
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ChatResponse(reply=reply_message, auto_escape=False)

    return router
