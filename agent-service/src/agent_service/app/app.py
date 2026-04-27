from threading import Lock

from ..router import create_router

from ..agent_core import AgentCore
from fastapi import FastAPI

from .config import get_settings, get_system_prompt

settings = get_settings()
system_prompt = get_system_prompt()

# 在进程启动时创建单例 AgentCore，保证工具注册与对话上下文在同一实例中连续演进。
# 如果改成按请求创建，会导致会话记忆被切断且重复初始化 MCP 连接。
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

app.include_router(create_router(agent=agent, agent_lock=agent_lock))
