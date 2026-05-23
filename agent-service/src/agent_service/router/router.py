import re

from fastapi import APIRouter, HTTPException

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..services import AgentRegistry
from .schemas import (
    ChatRequest,
    ChatResponse,
    CreateAgentRequest,
    CreateAgentResponse,
    HealthResponse,
)


def create_router(
    agent_registry: AgentRegistry,
) -> APIRouter:
    # 每次装配时创建独立路由对象，避免测试或重复初始化时重复注册同一路由。
    router = APIRouter()
    logger = get_logger("router")

    @router.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.post("/agents", response_model=CreateAgentResponse)
    def create_agent(req: CreateAgentRequest) -> CreateAgentResponse:
        agent = agent_registry.create(metadata=req.metadata)
        log_info(
            logger,
            "agent.agent_created",
            agent_id=agent.get_agent_id(),
        )
        return CreateAgentResponse(agent_id=agent.get_agent_id(), metadata=agent.metadata)

    @router.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        request_started_at = start_timer()
        agent = agent_registry.get(req.agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        event_count = _count_batch_events(req.batch)

        log_info(
            logger,
            "agent.chat_received",
            agent_id=req.agent_id,
            message_count=event_count,
        )

        try:
            reply = agent.run(
                user_message=req.batch,
                message_count=event_count,
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


def _count_batch_events(batch_xml: str) -> int:
    # 事件数只用于观测统计，按标签计数能避免批次内容格式变化导致统计失真。
    count = len(re.findall(r"<(?:message|poke|recall)\b", batch_xml))
    return count if count > 0 else 1

