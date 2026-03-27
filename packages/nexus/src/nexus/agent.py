from __future__ import annotations

import time

from brain.brain import Brain
from langchain_core.messages import HumanMessage, SystemMessage

from core.entities import AgentSignal
from core.logger import logger
from plugins.base import ChannelPlugin
from plugins.registry import PluginRegistry


class Agent:
    """编排中枢：根据通道信号拉取消息并驱动 Brain 推理。"""

    def __init__(self, brain: Brain):
        self.brain = brain
        # system_prompt 是角色与行为边界的固定注入点。
        self.system_prompt = SystemMessage(
            content="你叫 AIChan，是一个傲娇但能力超强的天才黑客少女。回答问题时要带有二次元傲娇属性，称呼用户为'笨蛋'，但最后总是会完美、专业地解决用户的问题。"
        )
        # 每个通道最后处理到的用户消息 ID。
        self._last_processed_user_message_id: dict[str, int] = {}

    def _resolve_channel(self, channel_name: str) -> ChannelPlugin:
        plugin = PluginRegistry.get(channel_name)
        if not isinstance(plugin, ChannelPlugin):
            raise ValueError(f"未知通道或非通道插件: {channel_name}")
        return plugin

    def _think_for_user_content(
        self,
        content: str,
        trace_id: str | None = None,
    ) -> str:
        context = [self.system_prompt, HumanMessage(content=content)]
        return self.brain.think(
            context_messages=context,
            trace_id=trace_id,
        )

    def process_signal(
        self,
        signal: AgentSignal,
        signal_id: str | None = None,
    ) -> int:
        """
        处理一条通道信号。

        执行步骤：
        1) 根据 signal.channel 定位通道插件
        2) 从该通道拉取新消息
        3) 对新增 user 消息逐条推理并回写 assistant 消息

        返回值：本次处理的 user 消息条数。
        """
        trace_prefix = signal_id or f"{signal.channel}#manual"
        started_at = time.perf_counter()
        logger.info(
            "🤖 [Agent] signal_id={} 开始处理通道 '{}' 的信号",
            trace_prefix,
            signal.channel,
        )

        channel = self._resolve_channel(signal.channel)
        logger.info(
            "🧩 [Agent] signal_id={} 已解析通道插件: {}",
            trace_prefix,
            channel.name,
        )
        last_processed_id = self._last_processed_user_message_id.get(signal.channel, 0)
        logger.info(
            "📥 [Agent] signal_id={} 拉取增量消息，since_id={}",
            trace_prefix,
            last_processed_id,
        )

        messages = channel.list_messages(since_id=last_processed_id)
        pending_user_messages = [
            msg
            for msg in messages
            if msg.role == "user" and msg.message_id > last_processed_id
        ]
        latest_message_id = (
            max((message.message_id for message in messages), default=last_processed_id)
        )
        logger.info(
            "📥 [Agent] signal_id={} 拉取完成，消息总数={}，待处理user消息={}，latest_message_id={}",
            trace_prefix,
            len(messages),
            len(pending_user_messages),
            latest_message_id,
        )

        if not pending_user_messages:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "✅ [Agent] signal_id={} 无待处理 user 消息，结束本轮信号，耗时={}ms",
                trace_prefix,
                elapsed_ms,
            )
            return 0

        total_pending = len(pending_user_messages)
        for index, user_msg in enumerate(pending_user_messages, start=1):
            msg_trace_id = (
                f"{trace_prefix}:user#{user_msg.message_id}:{index}/{total_pending}"
            )
            think_started_at = time.perf_counter()
            logger.info(
                "🧠 [Agent] trace_id={} 开始推理，用户消息长度={}字符",
                msg_trace_id,
                len(user_msg.content),
            )
            reply = self._think_for_user_content(
                content=user_msg.content,
                trace_id=msg_trace_id,
            )
            think_elapsed_ms = int((time.perf_counter() - think_started_at) * 1000)
            logger.info(
                "🧠 [Agent] trace_id={} 推理完成，回复长度={}字符，耗时={}ms",
                msg_trace_id,
                len(reply),
                think_elapsed_ms,
            )

            send_started_at = time.perf_counter()
            sent_message = channel.send_message(role="assistant", content=reply)
            send_elapsed_ms = int((time.perf_counter() - send_started_at) * 1000)
            logger.info(
                "📤 [Agent] trace_id={} 回复已写回通道 '{}'，assistant_message_id={}，耗时={}ms",
                msg_trace_id,
                sent_message.channel,
                sent_message.message_id,
                send_elapsed_ms,
            )
            self._last_processed_user_message_id[signal.channel] = user_msg.message_id
            logger.info(
                "🧷 [Agent] signal_id={} 更新通道 '{}' 的 last_processed_user_message_id={}",
                trace_prefix,
                signal.channel,
                user_msg.message_id,
            )

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "✅ [Agent] signal_id={} 处理结束，已处理user消息={}，总耗时={}ms",
            trace_prefix,
            total_pending,
            elapsed_ms,
        )
        return total_pending
