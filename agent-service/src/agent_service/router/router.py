from ..agent_core import AgentCore

from .schemas import ChatRequest, ChatResponse, HealthResponse
from threading import Lock

from fastapi import APIRouter, HTTPException


def create_router(agent: AgentCore, agent_lock: Lock) -> APIRouter:
    # 每次装配时创建独立路由对象，避免测试或重复初始化时重复注册同一路由。
    router = APIRouter()

    @router.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @router.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        try:
            # AgentCore 维护单进程内存态上下文；这里串行化请求，避免并发写入导致会话状态错乱。
            with agent_lock:
                reply = agent.chat(user_input=req.user_input, max_turns=req.max_turns)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return ChatResponse(reply=reply)

    return router
