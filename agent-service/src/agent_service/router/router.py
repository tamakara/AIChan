import re
import xml.etree.ElementTree as ET

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
            batch = agent.run(
                user_message=req.batch,
                message_count=event_count,
            )
            _validate_agent_batch_output(batch)
            log_info(
                logger,
                "agent.chat_completed",
                agent_id=req.agent_id,
                reply_len=len(batch),
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
        return ChatResponse(batch=batch)

    return router


def _count_batch_events(batch_xml: str) -> int:
    # 事件数只用于观测统计，按标签计数能避免批次内容格式变化导致统计失真。
    count = len(re.findall(r"<(?:message|poke|recall)\b", batch_xml))
    return count if count > 0 else 1


def _validate_agent_batch_output(batch_xml: str) -> None:
    try:
        root = ET.fromstring(batch_xml)
    except ET.ParseError as exc:
        raise ValueError("agent output must be valid xml") from exc

    if root.tag != "batch":
        raise ValueError("agent output root tag must be <batch>")
    if root.attrib.get("type") != "end":
        raise ValueError("agent output batch.type must be 'end'")
    if len(root) == 0:
        raise ValueError("agent output batch must include at least one event")

    # 这里在服务边界做强校验，防止非协议输出直接写入下游动作流导致执行层误操作。
    for child in root:
        session_id = child.attrib.get("session_id", "").strip()
        if not session_id:
            raise ValueError(f"agent output <{child.tag}> missing session_id")

        if child.tag == "message":
            content = (child.text or "").strip()
            if not content:
                raise ValueError("agent output <message> content must be non-empty")
            continue

        if child.tag == "poke":
            target_id = child.attrib.get("target_id", "").strip()
            if not target_id:
                raise ValueError("agent output <poke> missing target_id")
            continue

        if child.tag == "recall":
            message_id = child.attrib.get("message_id", "").strip()
            if not message_id:
                raise ValueError("agent output <recall> missing message_id")
            continue

        raise ValueError(f"agent output contains unsupported tag: {child.tag}")

