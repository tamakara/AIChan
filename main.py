from __future__ import annotations

import time

from langchain_openai import ChatOpenAI

from brain.brain import Brain
from core.config import settings
from core.entities import AgentSignal, ChannelMessage
from core.logger import logger
from nexus.agent import Agent
from plugins.base import BaseChannelPlugin
from plugins.channels.cli import CLIChannelPlugin
from plugins.registry import PluginRegistry
from plugins.tools.time_tool import CurrentTimeToolPlugin


def register_default_plugins() -> None:
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
    register_default_plugins()

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


def list_channel_messages(channel: BaseChannelPlugin, since_id: int) -> list[ChannelMessage]:
    return channel.list_messages(since_id=since_id)


def send_channel_message(channel: BaseChannelPlugin, role: str, content: str) -> None:
    channel.send_message(role=role, content=content)


def print_intro(channel_name: str) -> None:
    line = "=" * 64
    print(line)
    print("AIChan CLI")
    print(f"通道    : {channel_name}")
    print("提示    : 输入消息后回车发送，按 Ctrl+C 退出")
    print(line)


def print_channel_message(message: ChannelMessage) -> None:
    if message.role == "user":
        return

    speaker = "AIChan" if message.role == "assistant" else "System"
    content = message.content.strip()
    if not content:
        print(f"{speaker} > （空消息）")
    elif "\n" not in content:
        print(f"{speaker} > {content}")
    else:
        print(f"{speaker} >")
        for line in content.splitlines():
            print(f"  {line}")


def flush_channel_updates(channel: BaseChannelPlugin, since_id: int, elapsed_seconds: float) -> int:
    updates = list_channel_messages(channel=channel, since_id=since_id)
    if not updates:
        print("AIChan > （无新增消息）")
        return since_id

    newest_id = since_id
    printed_any = False
    for message in updates:
        newest_id = max(newest_id, message.message_id)
        if message.role != "user":
            print_channel_message(message)
            printed_any = True

    if printed_any:
        print(f"[耗时 {elapsed_seconds:.1f}s]")

    return newest_id


def run_cli(agent: Agent, channel: CLIChannelPlugin) -> None:
    print_intro(channel_name=channel.name)
    last_seen_id = 0

    while True:
        try:
            text = input("\n你 > ").strip()
        except KeyboardInterrupt:
            print("\n\n已退出 AIChan CLI。")
            break
        except EOFError:
            print("\n\n输入流已结束，AIChan CLI 已退出。")
            break

        if not text:
            print("AIChan > 请输入内容后再发送。")
            continue

        try:
            send_channel_message(channel=channel, role="user", content=text)
            print("AIChan 思考中...")
            started_at = time.perf_counter()
            agent.process_signal(AgentSignal(channel=channel.name))
            elapsed_seconds = time.perf_counter() - started_at
            last_seen_id = flush_channel_updates(
                channel=channel,
                since_id=last_seen_id,
                elapsed_seconds=elapsed_seconds,
            )
        except KeyboardInterrupt:
            print("\n\n推理已中断，AIChan CLI 已退出。")
            break
        except Exception as exc:
            logger.exception("聊天处理失败：{}", exc)
            print(f"AIChan > 处理失败：{exc}")


def main() -> None:
    """
    本地启动入口：组装核心模块并启动交互式 CLI。
    """
    agent = build_agent()
    cli_channel = resolve_cli_channel()
    logger.info("AIChan CLI 已启动，模型: {}", settings.llm_model_name)
    run_cli(agent=agent, channel=cli_channel)


if __name__ == "__main__":
    main()
