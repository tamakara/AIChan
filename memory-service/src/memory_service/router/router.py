from fastapi import APIRouter

from ..logger import elapsed_ms, get_logger, log_info, start_timer
from ..services import MemoryService
from .schemas import (
    CompressMemoryRequest,
    CompressMemoryResponse,
    HealthResponse,
    MemoryResponse,
    UserMemoryResponse,
)


def create_router(memory_service: MemoryService) -> APIRouter:
    router = APIRouter()
    logger = get_logger("router")

    @router.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse()

    @router.get("/api/v1/memories/{session_id}", response_model=MemoryResponse)
    def get_memory(session_id: str) -> MemoryResponse:
        return MemoryResponse(session_id=session_id, content_markdown=memory_service.read(session_id))

    @router.get("/api/v1/users/{user_id}/memory", response_model=UserMemoryResponse)
    def get_user_memory(user_id: str) -> UserMemoryResponse:
        return UserMemoryResponse(
            user_id=user_id,
            content_markdown=memory_service.read_user_memory(user_id),
        )

    @router.post("/api/v1/memories/{session_id}/compress", response_model=CompressMemoryResponse)
    def compress_memory(session_id: str, request: CompressMemoryRequest) -> CompressMemoryResponse:
        started_at = start_timer()
        result = memory_service.compress_and_append(
            session_id=session_id,
            messages_text=request.messages_text,
        )
        log_info(
            logger,
            "memory.compress_completed",
            session_id=session_id,
            added_count=result.added_count,
            elapsed_ms=elapsed_ms(started_at),
        )
        return CompressMemoryResponse(
            session_id=session_id,
            content_markdown=result.content_markdown,
            added_markdown=result.added_markdown,
            added_count=result.added_count,
        )

    return router
