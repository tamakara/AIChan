from __future__ import annotations

from cli import run_cli_loop
from langchain_openai import ChatOpenAI

from brain.brain import Brain
from core.config import settings
from core.logger import logger
from nexus.agent import Agent
from plugins.channels.cli import CLIChannelPlugin
from plugins.registry import PluginRegistry
from plugins.tools.time_tool import CurrentTimeToolPlugin


def register_plugins() -> None:
    """
    注册系统启动后的默认插件能力。

    说明：
    - cli: 终端会话通道
    - get_current_time: 时间工具能力
    """
    PluginRegistry.clear()
    PluginRegistry.register(CLIChannelPlugin())
    PluginRegistry.register(CurrentTimeToolPlugin())


def build_agent() -> Agent:
    """
    组装核心模块并返回 Agent（nexus）实例。

    组装顺序：
    1) 注册默认插件能力
    2) 初始化 LLM 并构建 brain
    3) 构建 nexus（Agent）
    """
    register_plugins()

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )

    # 仅工具插件会绑定到 LLM；通道插件不参与 LLM 工具调用。
    brain = Brain(llm_client=llm, tools=PluginRegistry.all_tools())
    return Agent(brain=brain)


def resolve_cli_channel() -> CLIChannelPlugin:
    plugin = PluginRegistry.get("cli")
    if not isinstance(plugin, CLIChannelPlugin):
        raise RuntimeError("CLIChannelPlugin 未注册")
    return plugin


def main() -> None:
    """
    本地启动入口：组装核心模块并启动交互式 CLI。
    """
    agent = build_agent()
    cli_channel = resolve_cli_channel()
    logger.info("AIChan CLI 已启动，模型: {}", settings.llm_model_name)
    run_cli_loop(agent=agent, channel=cli_channel)


if __name__ == "__main__":
    main()
