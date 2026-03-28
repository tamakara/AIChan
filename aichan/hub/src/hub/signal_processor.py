from __future__ import annotations

import time

from agent.agent import Agent

from core.entities import AgentSignal, ChannelMessage
from core.logger import logger
from plugins.base import ChannelPlugin
from plugins.registry import PluginRegistry


class SignalProcessor:
    """信号处理器：根据通道信号拉取消息并驱动 Agent 推理。"""

    def __init__(self, agent: Agent):
        self._agent = agent
        # 每个通道最后处理到的用户消息 ID。
        self._last_processed_user_message_id: dict[str, int] = {}

    def _resolve_channel(self, channel_name: str) -> ChannelPlugin:
        plugin = PluginRegistry.get(channel_name)
        if not isinstance(plugin, ChannelPlugin):
            raise ValueError(f"未知通道或非通道插件: {channel_name}")
        return plugin

    @staticmethod
    def _split_old_new_messages(
        all_messages: list[ChannelMessage],
        last_processed_id: int,
    ) -> tuple[list[ChannelMessage], list[ChannelMessage]]:
        ordered_messages = sorted(all_messages, key=lambda m: m.message_id)
        old_messages = [m for m in ordered_messages if m.message_id <= last_processed_id]
        new_messages = [m for m in ordered_messages if m.message_id > last_processed_id]
        return old_messages, new_messages

    def process_signal(
        self,
        signal: AgentSignal,
        signal_id: str | None = None,
    ) -> int:
        """
        处理一条通道信号。

        执行步骤：
        1) 根据 signal.channel 定位通道插件
        2) 拉取通道消息并拆分为 old/new 列表
        3) 将 old/new 列表一次性传递给 agent 推理并回写 assistant 消息

        返回值：本次处理的新 user 消息条数。
        """
        trace_prefix = signal_id or f"{signal.channel}#manual"
        started_at = time.perf_counter()
        logger.info(
            "🚀 [Signal] signal_id={} 开始处理通道 '{}'",
            trace_prefix,
            signal.channel,
        )

        channel = self._resolve_channel(signal.channel)
        last_processed_id = self._last_processed_user_message_id.get(signal.channel, 0)

        all_messages = channel.list_messages(since_id=0)
        old_messages, new_messages = self._split_old_new_messages(
            all_messages=all_messages,
            last_processed_id=last_processed_id,
        )
        pending_user_messages = [msg for msg in new_messages if msg.role == "user"]
        latest_message_id = (
            max((message.message_id for message in all_messages), default=last_processed_id)
        )
        logger.info(
            "📊 [Signal] signal_id={} 消息数量 all={} old={} new={} 待处理user={} latest_message_id={}",
            trace_prefix,
            len(all_messages),
            len(old_messages),
            len(new_messages),
            len(pending_user_messages),
            latest_message_id,
        )

        if not pending_user_messages:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "✅ [Signal] signal_id={} 处理完成（无待处理user），耗时={}ms",
                trace_prefix,
                elapsed_ms,
            )
            return 0

        total_pending = len(pending_user_messages)
        msg_trace_id = (
            f"{trace_prefix}:batch_user#{pending_user_messages[0].message_id}"
            f"-{pending_user_messages[-1].message_id}:count={total_pending}"
        )
        reply = self._agent.think(
            old_messages=old_messages,
            new_messages=new_messages,
            trace_id=msg_trace_id,
        )

        sent_message = channel.send_message(role="assistant", content=reply)

        latest_user_message_id = max(msg.message_id for msg in pending_user_messages)
        self._last_processed_user_message_id[signal.channel] = latest_user_message_id

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "✅ [Signal] signal_id={} 处理完成，已处理user={} assistant_message_id={} 耗时={}ms",
            trace_prefix,
            total_pending,
            sent_message.message_id,
            elapsed_ms,
        )
        return total_pending
