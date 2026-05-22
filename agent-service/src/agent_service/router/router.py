from fastapi import APIRouter, HTTPException

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..services import AgentRunRegistry, render_messages_xml
from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateAgentRunRequest,
    CreateAgentRunResponse,
    HealthResponse,
)


def create_router(
    agent_run_registry: AgentRunRegistry,
) -> APIRouter:
    # 每次装配时创建独立路由对象，避免测试或重复初始化时重复注册同一路由。
    router = APIRouter()
    logger = get_logger("router")

    @router.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.post("/agent-runs", response_model=CreateAgentRunResponse)
    def create_agent_run(req: CreateAgentRunRequest) -> CreateAgentRunResponse:
        agent_run = agent_run_registry.create(metadata=req.metadata)
        log_info(
            logger,
            "agent.agent_run_created",
            agent_id=agent_run.get_agent_id(),
        )
        return CreateAgentRunResponse(agent_id=agent_run.get_agent_id(), metadata=agent_run.metadata)

    @router.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        request_started_at = start_timer()
        agent_run = agent_run_registry.get(req.agent_id)
        if agent_run is None:
            raise HTTPException(status_code=404, detail="agent_run not found")

        metadata = agent_run.metadata
        metadata["agent_id"] = agent_run.get_agent_id()

        log_info(
            logger,
            "agent.chat_received",
            agent_id=req.agent_id,
            message_count=len(req.messages),
        )

        try:
            user_message = render_messages_xml(
                metadata=metadata,
                messages=req.messages,
            )
            reply = agent_run.run(
                user_message=user_message,
                message_count=len(req.messages),
            )
            log_info(
                logger,
                "agent.chat_completed",
                agent_id=req.agent_id,
                reply_len=len(reply),
                elapsed_ms=elapsed_ms(request_started_at),
            )
        except Exception as exc:
            log_exception(
                logger,
                "agent.chat_failed",
                agent_id=req.agent_id,
                elapsed_ms=elapsed_ms(request_started_at),
            )
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ChatResponse(reply=reply)

    return router
