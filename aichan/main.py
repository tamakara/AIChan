from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse
import re

import uvicorn
from fastapi import FastAPI
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent import WakeUpAgentRuntime
from core.config import settings
from core.logger import logger
from mcp_hub import MCPManager, MCPServerConfig


def build_llm_client() -> BaseChatModel:
    """
    构建 LLM 客户端。
    """
    return ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )


def build_mcp_server_configs(raw_urls: list[str]) -> list[MCPServerConfig]:
    """
    将环境变量中的 MCP URL 列表解析为标准配置。

    约定：
    - 允许多个 URL；
    - 自动生成稳定服务别名；
    - 当前版本默认全部视为强依赖服务。
    """
    parsed_urls = [item.strip() for item in raw_urls if item and item.strip()]
    if not parsed_urls:
        parsed_urls = ["http://localhost:9000/mcp/sse"]

    configs: list[MCPServerConfig] = []
    used_aliases: set[str] = set()
    for index, url in enumerate(parsed_urls, start=1):
        parsed = urlparse(url)
        raw_alias = parsed.netloc or f"mcp_{index}"
        alias = re.sub(r"[^A-Za-z0-9_]+", "_", raw_alias).strip("_").lower()
        if not alias:
            alias = f"mcp_{index}"
        if alias[0].isdigit():
            alias = f"mcp_{alias}"

        if alias in used_aliases:
            alias = f"{alias}_{index}"
        used_aliases.add(alias)

        configs.append(
            MCPServerConfig(
                name=alias,
                sse_url=url,
                required=True,
            )
        )
    return configs


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动阶段：
    1. 初始化 MCPManager；
    2. 启动 WakeUpAgentRuntime。

    关闭阶段：
    1. 停止 WakeUpAgentRuntime；
    2. 停止 MCPManager。
    """
    logger.info("🚀 [Main] AICHAN 大脑生命周期启动中（Pull + Tool-as-Action）")

    server_configs = build_mcp_server_configs(settings.mcp_server_urls)
    mcp_manager = MCPManager(
        server_configs=server_configs,
    )
    await mcp_manager.start()

    wakeup_runtime = WakeUpAgentRuntime(
        llm_factory=build_llm_client,
        mcp_manager=mcp_manager,
    )
    await wakeup_runtime.start()

    app.state.mcp_manager = mcp_manager
    app.state.wakeup_runtime = wakeup_runtime

    try:
        yield
    finally:
        logger.info("🛑 [Main] AICHAN 大脑生命周期关闭中")
        await wakeup_runtime.stop()
        await mcp_manager.stop()
        logger.info("✅ [Main] AICHAN 大脑已停止")


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
        mcp_manager: MCPManager | None = getattr(app.state, "mcp_manager", None)
        mcp_tool_count = 0
        mcp_server_count = 0
        wakeup_queue_size = 0
        if mcp_manager is not None:
            mcp_server_count = mcp_manager.get_connected_server_count()
            mcp_tool_count = len(await mcp_manager.get_all_tools(refresh=False))
            wakeup_queue_size = mcp_manager.get_wakeup_queue().qsize()

        return {
            "ok": True,
            "service": "aichan_brain",
            "mcp_server_count": mcp_server_count,
            "mcp_tool_count": mcp_tool_count,
            "wakeup_queue_size": wakeup_queue_size,
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
