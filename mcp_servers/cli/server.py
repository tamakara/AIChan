from __future__ import annotations

import uvicorn
from loguru import logger

from .app import build_cli_mcp_app
from .settings import (
    CLI_SERVER_HOST,
    CLI_SERVER_PORT,
    CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
)

"""
CLI MCP Server 启动入口。

该文件只负责进程启动，不承载业务逻辑。
"""


def main() -> None:
    """启动 Uvicorn 并加载已装配好的 FastAPI 应用。"""
    logger.info("🚀 [CLIServer] 准备启动，混合原生 MCP + FastAPI...")
    uvicorn.run(
        build_cli_mcp_app(),
        host=CLI_SERVER_HOST,
        port=CLI_SERVER_PORT,
        log_level="info",
        access_log=False,
        timeout_keep_alive=CLI_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS,
        timeout_graceful_shutdown=CLI_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS,
    )


if __name__ == "__main__":
    main()
