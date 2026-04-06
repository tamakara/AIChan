"""
AICHAN Brain 服务主入口。

模块职责：
1. 读取配置并装配运行时依赖；
2. 解析 MCP 端点并启动 MCP 管理器；
3. 装配 AgentRuntime，建立唤醒驱动的推理循环；
4. 暴露 FastAPI 健康检查与服务生命周期。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI

from agent import AgentRuntime
from core.config import settings
from core.logger import logger
from mcp_hub import MCPManager


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动阶段：
    1. 初始化 MCPManager；
    2. 启动 AgentRuntime。

    关闭阶段：
    1. 停止 AgentRuntime；
    2. 停止 MCPManager。
    """
    logger.info("🚀 [Main] AICHAN 生命周期启动中...")

    mcp_manager = MCPManager(
        reconnect_seconds=settings.mcp_connect_retry_seconds,
    )
    await mcp_manager.connect(settings.mcp_server_endpoints)

    agent_runtime = AgentRuntime(
        llm_api_type=settings.llm_api_type,
        llm_api_key=settings.llm_api_key.get_secret_value(),
        llm_base_url=settings.llm_base_url,
        llm_model_name=settings.llm_model_name,
        llm_temperature=settings.llm_temperature,
        mcp_manager=mcp_manager,
    )
    await agent_runtime.start()

    app.state.mcp_manager = mcp_manager
    app.state.agent_runtime = agent_runtime

    try:
        yield
    finally:
        logger.info("🛑 [Main] AICHAN 生命周期关闭中")
        await agent_runtime.stop()
        await mcp_manager.close()
        logger.info("✅ [Main] AICHAN 已停止")


def create_app() -> FastAPI:
    """
    创建 AICHAN 大脑应用。

    路由构成：
    - `/health`：基础健康检查。
    """
    app = FastAPI(
        title="AICHAN",
        version="1.0.0",
        lifespan=app_lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """
        健康检查端点。

        除基础存活状态外，还会返回 MCP 连接数量、工具数量以及最近唤醒快照，
        便于运维快速判断系统当前是否具备完整工作能力。
        """
        mcp_manager: MCPManager | None = getattr(app.state, "mcp_manager", None)
        mcp_tool_count = 0
        mcp_server_count = 0
        wakeup_event_is_set = False
        last_wakeup: dict[str, Any] | None = None
        if mcp_manager is not None:
            mcp_server_count = mcp_manager.get_connected_server_count()
            mcp_tool_count = len(await mcp_manager.get_all_tools(refresh=False))
            wakeup_event_is_set = mcp_manager.get_wakeup_event().is_set()
            last_wakeup = mcp_manager.get_last_wakeup_snapshot()

        return {
            "ok": True,
            "service": "aichan_brain",
            "mcp_server_count": mcp_server_count,
            "mcp_tool_count": mcp_tool_count,
            "wakeup_event_is_set": wakeup_event_is_set,
            "last_wakeup": last_wakeup,
        }

    return app


app = create_app()


def main() -> None:
    """直接启动 AICHAN 大脑服务。"""
    logger.info("🚀 [Main] AICHAN Brain 启动中，监听 0.0.0.0:8000")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
