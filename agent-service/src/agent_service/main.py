from threading import Lock

import uvicorn
from fastapi import FastAPI, HTTPException

from .agent_core import AgentCore
from .config import get_settings, get_system_prompt
from .schemas import ChatRequest, ChatResponse, HealthResponse

settings = get_settings()
system_prompt = get_system_prompt()
agent = AgentCore(
    llm_model_name=settings.llm_model_name,
    llm_api_key=settings.llm_api_key,
    llm_base_url=settings.llm_base_url,
    system_prompt=system_prompt,
    mcp_gateway_sse_url=settings.mcp_gateway_sse_url,
    mcp_gateway_auth_token=settings.mcp_gateway_auth_token,
)
agent_lock = Lock()

app = FastAPI(
    title="agent-service FastAPI service",
    version="0.1.0",
    description="HTTP API wrapper around AgentCore.",
)

@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        with agent_lock:
            reply = agent.chat(user_input=req.user_input, max_turns=req.max_turns)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(reply=reply)


def run() -> None:
    uvicorn.run(
        "agent_service.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )
