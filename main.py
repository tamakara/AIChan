from __future__ import annotations

import uvicorn
from langchain_openai import ChatOpenAI

from brain.brain import Brain
from cli_server import create_app
from core.config import settings
from core.logger import logger
from peripherals.channels.cli import CLIChannelPeripheral
from peripherals.registry import PeripheralRegistry
from peripherals.tools.time_tool import CurrentTimeToolPeripheral
from synapse.agent import AgentOrchestrator


def register_default_peripherals() -> None:
    """
    注册系统启动后的默认外设能力。

    说明：
    - `cli` 属于交互通道能力（负责把外部负载转成 UserMessage）
    - `get_current_time` 属于工具能力（可被 LLM 调用）
    """
    PeripheralRegistry.clear()
    PeripheralRegistry.register("cli", CLIChannelPeripheral())
    PeripheralRegistry.register("get_current_time", CurrentTimeToolPeripheral())


def build_orchestrator() -> AgentOrchestrator:
    """
    组装核心模块并返回编排器（synapse）实例。

    组装顺序：
    1) 注册默认外设能力
    2) 初始化 LLM 并构建 brain
    3) 构建 synapse（AgentOrchestrator）
    """
    register_default_peripherals()

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )

    brain = Brain(llm_client=llm, tools=PeripheralRegistry.all_tools())
    return AgentOrchestrator(brain=brain)


def main() -> None:
    """
    本地启动入口：先完成系统模块组装，再启动 HTTP 服务。
    """
    orchestrator = build_orchestrator()
    app = create_app(orchestrator)

    logger.info(
        "AIChan 服务已启动：http://{}:{}",
        settings.chat_server_host,
        settings.chat_server_port,
    )
    logger.info("请在另一个终端运行 `uv run python cli_client.py` 发起对话。")

    uvicorn.run(
        app,
        host=settings.chat_server_host,
        port=settings.chat_server_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
