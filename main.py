from __future__ import annotations

import threading
import time

from langchain_openai import ChatOpenAI

from brain.brain import Brain
from cli_server import CLI_SERVER_BASE_URL, CLIServerRuntime
from core.config import settings
from core.entities import AgentSignal
from core.logger import logger
from nexus.agent import Agent
from nexus.hub import nexus_hub
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


def build_agent() -> Agent:
    """组装核心模块并返回 Agent。"""
    register_plugins()

    llm = ChatOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model_name,
        temperature=settings.llm_temperature,
    )

    brain = Brain(llm_client=llm, tools=PluginRegistry.all_tools())
    return Agent(brain=brain)


def resolve_cli_channel() -> CLIChannelPlugin:
    plugin = PluginRegistry.get("cli")
    if not isinstance(plugin, CLIChannelPlugin):
        raise RuntimeError("CLIChannelPlugin 未注册")
    return plugin


def start_cli_unread_poller(
    cli_channel: CLIChannelPlugin,
    interval_seconds: float = 1.0,
) -> tuple[threading.Event, threading.Thread]:
    """
    启动未读轮询线程：
    - 每 interval_seconds 查询一次 AI 侧是否有未读消息
    - 有未读时由 plugin 触发新信号入 NexusHub
    """
    stop_event = threading.Event()

    def _poll_loop() -> None:
        while not stop_event.is_set():
            try:
                emitted = cli_channel.emit_signal_if_ai_unread(
                    emit_signal=lambda channel_name: nexus_hub.push_signal(
                        AgentSignal(channel=channel_name)
                    )
                )
                if emitted:
                    logger.info("🔔 [Main] 检测到 CLI 未读，已发出 AgentSignal")
            except Exception as exc:
                logger.exception("CLI 未读轮询失败：{}", exc)
            finally:
                stop_event.wait(interval_seconds)

    worker = threading.Thread(
        target=_poll_loop,
        name="cli-unread-poller",
        daemon=True,
    )
    worker.start()
    return stop_event, worker


def stop_cli_unread_poller(
    stop_event: threading.Event,
    worker: threading.Thread,
) -> None:
    """停止未读轮询线程。"""
    stop_event.set()
    if worker.is_alive():
        worker.join(timeout=3.0)


def main() -> None:
    """
    本地启动入口：运行 AIChan 核心并内嵌启动 cli_server。
    """
    agent = build_agent()
    cli_channel = resolve_cli_channel()
    nexus_hub.bind_agent(agent)
    nexus_hub.start_heartbeat()

    cli_server = CLIServerRuntime()
    poller_stop_event: threading.Event | None = None
    poller_thread: threading.Thread | None = None

    try:
        cli_server.start()
        poller_stop_event, poller_thread = start_cli_unread_poller(
            cli_channel=cli_channel,
            interval_seconds=1.0,
        )

        logger.info("AIChan 服务已启动，模型: {}", settings.llm_model_name)
        logger.info("CLI 外部聊天服务地址: {}", CLI_SERVER_BASE_URL)
        logger.info("CLI 未读轮询间隔: 1 秒")
        logger.info("请在另一个终端启动客户端: uv run python cli_client.py")

        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("收到退出信号，正在关闭服务")
    finally:
        if poller_stop_event is not None and poller_thread is not None:
            stop_cli_unread_poller(
                stop_event=poller_stop_event,
                worker=poller_thread,
            )
        cli_server.stop(wait=True)
        nexus_hub.stop_heartbeat(wait=True)


if __name__ == "__main__":
    main()
