from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from langchain_openai import ChatOpenAI

from core.config import settings
from core.logger import logger
from hub.registry_signal_trigger import RegistrySignalTrigger
from hub.signal_hub import SignalHub
from hub.signal_processor import SignalProcessor
from registry.routes import registry_router
from registry.state import (
    gateway_config_registry,
    gateway_tools_registry,
    global_event_bus,
)


def build_llm_client() -> ChatOpenAI:
    """
    构建 LLM 客户端。

    本项目采用“无兼容降级”策略，启动时要求关键环境变量全部可用。
    """
    return ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动阶段：
    1. 初始化 SignalProcessor；
    2. 启动 SignalHub 心跳主循环；
    3. 启动注册中心事件触发器。

    关闭阶段：
    1. 停止事件触发器；
    2. 停止 SignalHub。
    """
    logger.info("🚀 [Main] AICHAN 大脑生命周期启动中（Registry + SignalHub）")

    signal_processor = SignalProcessor(
        llm_factory=build_llm_client,
        gateway_config_registry=gateway_config_registry,
        gateway_tools_registry=gateway_tools_registry,
    )
    signal_hub = SignalHub(signal_processor=signal_processor)
    signal_hub.start_heartbeat()

    signal_trigger = RegistrySignalTrigger(
        signal_hub=signal_hub,
        global_event_bus=global_event_bus,
        gateway_config_registry=gateway_config_registry,
    )
    await signal_trigger.start()

    app.state.signal_processor = signal_processor
    app.state.signal_hub = signal_hub
    app.state.signal_trigger = signal_trigger

    try:
        yield
    finally:
        logger.info("🛑 [Main] AICHAN 大脑生命周期关闭中")
        await signal_trigger.stop()
        signal_hub.stop_heartbeat(wait=True)
        logger.info("✅ [Main] AICHAN 大脑已停止")


def create_app() -> FastAPI:
    """
    创建 AICHAN 大脑应用。

    路由构成：
    - `registry_router`：网关注册中心；
    - `/health`：基础健康检查。
    """
    app = FastAPI(
        title="AICHAN Brain",
        version="3.0.0",
        lifespan=app_lifespan,
    )
    app.include_router(registry_router)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "aichan_brain",
            "gateway_count": len(gateway_config_registry),
            "tool_gateway_count": len(gateway_tools_registry),
            "event_queue_size": global_event_bus.qsize(),
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
