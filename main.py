from __future__ import annotations

import time

from agent.agent import Agent
from langchain_openai import ChatOpenAI

from cli_server import CLI_SERVER_BASE_URL, CLIServerRuntime
from core.config import settings
from core.logger import logger
from hub.cli_unread_poller import CLIUnreadPoller
from hub.signal_hub import SignalHub
from hub.signal_processor import SignalProcessor
from plugins.channels.cli import CLIChannelPlugin
from plugins.registry import PluginRegistry
from plugins.tools.time_tool import CurrentTimeToolPlugin


def register_plugins() -> None:
    """
    注册默认插件：
    - cli 通道插件（通过 HTTP 访问外部 cli_server）
    - get_current_time 工具插件
    """
    PluginRegistry.clear()
    PluginRegistry.register(CLIChannelPlugin())
    PluginRegistry.register(CurrentTimeToolPlugin())


def build_signal_processor() -> SignalProcessor:
    """组装核心模块并返回 SignalProcessor。"""
    register_plugins()

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )

    agent_runtime = Agent(llm_client=llm, tools=PluginRegistry.all_tools())
    return SignalProcessor(agent_runtime=agent_runtime)


def main() -> None:
    """
    本地启动入口：运行 AIChan 核心并内嵌启动 CLI Channel Server。
    """
    signal_processor = build_signal_processor()
    signal_hub = SignalHub(signal_processor=signal_processor)
    signal_hub.start_heartbeat()

    cli_server = CLIServerRuntime()
    cli_unread_poller: CLIUnreadPoller | None = None
    try:
        cli_server.start()
        plugin = PluginRegistry.get("cli")
        if not isinstance(plugin, CLIChannelPlugin):
            raise RuntimeError("CLIChannelPlugin 未注册")

        cli_unread_poller = CLIUnreadPoller(
            cli_channel=plugin,
            signal_hub=signal_hub,
            interval_seconds=1.0,
        )
        cli_unread_poller.start()

        logger.info("AIChan 服务已启动，模型: {}", settings.llm_model_name)
        logger.info("CLI 外部聊天服务地址: {}", CLI_SERVER_BASE_URL)
        logger.info("CLI 未读轮询间隔: 1 秒")
        logger.info("请在另一个终端启动客户端: uv run python cli_client.py")

        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务")
    finally:
        if cli_unread_poller is not None:
            cli_unread_poller.stop()
        cli_server.stop(wait=True)
        signal_hub.stop_heartbeat(wait=True)


if __name__ == "__main__":
    main()
