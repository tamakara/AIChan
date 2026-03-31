from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI
from loguru import logger

from cli_api import register_cli_api_routes
from cli_server import CLIMessageService

# ==========================================
# ⚙️ 全局默认配置常量
# ==========================================
CLI_SERVER_HOST = os.getenv("CLI_SERVER_HOST", "localhost")
CLI_SERVER_PORT = int(os.getenv("CLI_SERVER_PORT", "9000"))
CLI_GATEWAY_BASE_HOST = os.getenv("CLI_GATEWAY_HOST", "localhost")

# Uvicorn 服务器配置
CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS = 1
CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS = 2

# SSE 与注册中心配置
REGISTRY_RETRY_SECONDS = 3.0
AICHAN_REGISTRY_URL = os.getenv(
    "AICHAN_REGISTRY_URL", "http://localhost:8000/internal/registry/register"
)


# ==========================================
# 🔌 注册中心交互与生命周期
# ==========================================
def _build_registry_payload() -> dict[str, Any]:
    """构建 CLI 网关注册载荷"""
    return {
        "name": "cli",
        "type": "channel",
        "base_url": f"http://{CLI_GATEWAY_BASE_HOST}:{CLI_SERVER_PORT}",
        "openapi_path": "/openapi.json",
        "sse_path": "/v1/events",
    }


async def register_to_registry_loop() -> None:
    """后台异步无限重试：向 AICHAN 大脑注册当前网关"""
    payload = _build_registry_payload()
    while True:
        try:
            logger.info("🔌 [CLIGateway] 尝试注册到大脑，url='{}'", AICHAN_REGISTRY_URL)
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(AICHAN_REGISTRY_URL, json=payload)
                response.raise_for_status()
            logger.info("✅ [CLIGateway] 接入大脑成功！")
            return
        except asyncio.CancelledError:
            logger.info("🛑 [CLIGateway] 注册任务收到取消信号，结束后台注册")
            raise
        except Exception as exc:
            logger.error(
                "❌ [CLIGateway] 注册失败，error='{}'，{} 秒后重试",
                exc,
                REGISTRY_RETRY_SECONDS,
            )
            await asyncio.sleep(REGISTRY_RETRY_SECONDS)


@asynccontextmanager
async def gateway_lifespan(app: FastAPI):
    """网关生命周期管理：启动注册任务，关闭时清理资源"""
    logger.info("🚀 [CLIGateway] 服务启动，注册任务准备就绪")
    registration_task = asyncio.create_task(
        register_to_registry_loop(),
        name="cli-gateway-registry-registration",
    )
    app.state.registration_task = registration_task

    yield

    logger.info("🛑 [CLIGateway] 服务关闭中，清理后台任务")
    registration_task.cancel()
    with suppress(asyncio.CancelledError):
        await registration_task


# ==========================================
# 🌐 FastAPI 路由绑定
# ==========================================
def build_cli_gateway_app() -> FastAPI:
    """构建并配置 CLI 网关 FastAPI 应用"""
    app = FastAPI(
        title="CLI Gateway Server",
        version="2.0.0",
        lifespan=gateway_lifespan,
    )
    service = CLIMessageService()
    register_cli_api_routes(app, service)

    return app


# ==========================================
# 🚀 启动入口
# ==========================================
def run_cli_gateway(host: str = CLI_SERVER_HOST, port: int = CLI_SERVER_PORT) -> None:
    logger.info("🚀 [CLIGateway] 准备在 {}:{} 启动服务...", host, port)
    uvicorn.run(
        build_cli_gateway_app(),
        host=host,
        port=port,
        log_level="info",
        access_log=True,
        timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
        timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    )


def main() -> None:
    run_cli_gateway()


if __name__ == "__main__":
    main()
