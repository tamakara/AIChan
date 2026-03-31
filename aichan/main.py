from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse
import re

import uvicorn
from fastapi import FastAPI
from langchain_openai import ChatOpenAI

from core.config import settings
from core.logger import logger
from hub.channel_poll_trigger import ChannelPollTrigger
from hub.signal_hub import SignalHub
from hub.signal_processor import SignalProcessor
from mcp_hub import MCPManager, MCPServerConfig


def build_llm_client() -> ChatOpenAI:
    """
    构建 LLM 客户端。
    """
    return ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )


def build_mcp_server_configs(raw_urls: str) -> list[MCPServerConfig]:
    """
    将环境变量中的 MCP URL 列表解析为标准配置。

    约定：
    - 逗号分隔多个 URL；
    - 自动生成稳定服务别名；
    - 当前版本默认全部视为强依赖服务。
    """
    parsed_urls = [item.strip() for item in raw_urls.split(",") if item.strip()]
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


def build_channel_config_registry(
    server_configs: list[MCPServerConfig],
) -> dict[str, dict[str, str]]:
    """
    基于 MCP Server 配置构造通道配置映射。

    约定：
    - 通道名与 MCP Server 别名一致；
    - 通道 base_url 取 MCP SSE 地址的 origin（scheme + netloc）。
    """
    channel_config_registry: dict[str, dict[str, str]] = {}
    for config in server_configs:
        parsed = urlparse(config.sse_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"MCP_SERVER_URLS 中存在非法 URL：{config.sse_url}")
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        channel_config_registry[config.name] = {
            "gateway_type": "channel",
            "base_url": base_url,
        }
    return channel_config_registry


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动阶段：
    1. 初始化 SignalProcessor；
    2. 启动 SignalHub 心跳主循环；
    3. 启动通道轮询触发器。

    关闭阶段：
    1. 停止轮询触发器；
    2. 停止 SignalHub。
    """
    logger.info("🚀 [Main] AICHAN 大脑生命周期启动中（MCPHub + SignalHub）")

    server_configs = build_mcp_server_configs(settings.mcp_server_urls)
    mcp_manager = MCPManager(
        server_configs=server_configs,
    )
    await mcp_manager.start()

    channel_config_registry = build_channel_config_registry(server_configs)
    signal_processor = SignalProcessor(
        llm_factory=build_llm_client,
        channel_config_registry=channel_config_registry,
        mcp_manager=mcp_manager,
    )
    signal_hub = SignalHub(signal_processor=signal_processor)
    signal_hub.start_heartbeat()

    signal_trigger = ChannelPollTrigger(
        signal_hub=signal_hub,
        channel_config_registry=channel_config_registry,
    )
    await signal_trigger.start()

    app.state.signal_processor = signal_processor
    app.state.signal_hub = signal_hub
    app.state.signal_trigger = signal_trigger
    app.state.mcp_manager = mcp_manager
    app.state.channel_config_registry = channel_config_registry

    try:
        yield
    finally:
        logger.info("🛑 [Main] AICHAN 大脑生命周期关闭中")
        await signal_trigger.stop()
        signal_hub.stop_heartbeat(wait=True)
        await mcp_manager.stop()
        logger.info("✅ [Main] AICHAN 大脑已停止")


def create_app() -> FastAPI:
    """
    创建 AICHAN 大脑应用。

    路由构成：
    - `/health`：基础健康检查。
    """
    app = FastAPI(
        title="AICHAN Brain",
        version="3.0.0",
        lifespan=app_lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        mcp_manager: MCPManager | None = getattr(app.state, "mcp_manager", None)
        signal_hub: SignalHub | None = getattr(app.state, "signal_hub", None)
        channel_config_registry: dict[str, Any] = getattr(
            app.state, "channel_config_registry", {}
        )
        mcp_tool_count = 0
        mcp_server_count = 0
        queue_size = 0
        if mcp_manager is not None:
            mcp_server_count = mcp_manager.get_connected_server_count()
            mcp_tool_count = len(await mcp_manager.get_all_tools(refresh=False))
        if signal_hub is not None:
            queue_size = signal_hub.signal_queue.qsize()

        return {
            "ok": True,
            "service": "aichan_brain",
            "channel_count": len(channel_config_registry),
            "mcp_server_count": mcp_server_count,
            "mcp_tool_count": mcp_tool_count,
            "signal_queue_size": queue_size,
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
