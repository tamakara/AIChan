from fastapi import APIRouter, HTTPException

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..services import Agent, SessionRegistry
from ..services.session import SessionInterrupted
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
            session_id=session.session_id,
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
            session_id=session_id,
        )
        return {"deleted": True}

    @router.post("/sessions/{session_id}/interrupt")
    def interrupt_session(session_id: str) -> dict:
        ok = session_registry.interrupt(session_id)
        if not ok:
            raise HTTPException(status_code=404, detail="session not found")
        return {"interrupted": True}

    @router.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        request_started_at = start_timer()
        session = session_registry.get(req.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")

        log_info(
            logger,
            "agent.chat_received",
            session_id=req.session_id,
            message_len=len(req.input_xml),
        )

        try:
            reply = agent.run(
                session=session,
                user_message=req.input_xml,
            )
            log_info(
                logger,
                "agent.chat_completed",
                session_id=req.session_id,
                reply_len=len(reply.output_xml),
                elapsed_ms=elapsed_ms(request_started_at),
            )
        except SessionInterrupted:
            raise HTTPException(status_code=409, detail="session interrupted")
        except Exception as exc:
            log_exception(
                logger,
                "agent.chat_failed",
                session_id=req.session_id,
                elapsed_ms=elapsed_ms(request_started_at),
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ChatResponse(output_xml=reply.output_xml)

    return router
