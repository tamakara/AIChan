from __future__ import annotations

import time

from agent.agent import Agent
from langchain_openai import ChatOpenAI

from core.config import settings
from core.logger import logger
from hub.cli_sse_listener import CLIMessageSSEListener
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

def main() -> None:
    """
    本地启动入口：仅运行 AIChan 核心，依赖外部独立运行的 CLI Channel Server。
    """
    register_plugins()

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )
    agent = Agent(llm_client=llm, tools=PluginRegistry.all_tools())
    signal_processor = SignalProcessor(agent=agent)
    signal_hub = SignalHub(signal_processor=signal_processor)
    signal_hub.start_heartbeat()

    
    plugin = PluginRegistry.get("cli")
    if not isinstance(plugin, CLIChannelPlugin):
        raise RuntimeError("CLIChannelPlugin 未注册")

    cli_server_base_url = settings.cli_server_base_url
    cli_sse_listener = CLIMessageSSEListener(
        channel_name=plugin.name,
        signal_hub=signal_hub,
        server_base_url=cli_server_base_url,
    )
    
    try:
        cli_sse_listener.start()

        logger.info("AIChan 服务已启动，模型: {}", settings.llm_model_name)
        logger.info("CLI 外部聊天服务地址: {}", cli_server_base_url)
        logger.info("CLI 消息接入方式: SSE (/v1/events)")
        logger.info("请先在另一个终端启动服务: uv run python .\\cli_server\\cli_server.py")
        logger.info("再启动客户端: uv run python .\\cli_client\\cli_client.py")

        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务")
    finally:
        if cli_sse_listener is not None:
            cli_sse_listener.stop()
        signal_hub.stop_heartbeat(wait=True)


if __name__ == "__main__":
    main()
