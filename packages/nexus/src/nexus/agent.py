from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from core.entities import AgentSignal
from core.interfaces import IReasoningEngine
from plugins.base import BaseChannelPlugin
from plugins.registry import PluginRegistry


class Agent:
    """编排中枢：根据通道信号拉取消息并驱动 Brain 推理。"""

    def __init__(self, brain: IReasoningEngine):
        self.brain = brain
        # system_prompt 是角色与行为边界的固定注入点。
        self.system_prompt = SystemMessage(
            content="你叫 AIChan，是一个傲娇但能力超强的天才黑客少女。回答问题时要带有二次元傲娇属性，称呼用户为'笨蛋'，但最后总是会完美、专业地解决用户的问题。"
        )
        # 每个通道最后处理到的用户消息 ID。
        self._last_processed_user_message_id: dict[str, int] = {}

    def _resolve_channel(self, channel_name: str) -> BaseChannelPlugin:
        plugin = PluginRegistry.get(channel_name)
        if not isinstance(plugin, BaseChannelPlugin):
            raise ValueError(f"未知通道或非通道插件: {channel_name}")
        return plugin

    def _think_for_user_content(self, content: str) -> str:
        context = [self.system_prompt, HumanMessage(content=content)]
        return self.brain.think(context_messages=context)

    def process_signal(self, signal: AgentSignal) -> int:
        """
        处理一条通道信号。

        执行步骤：
        1) 根据 signal.channel 定位通道插件
        2) 从该通道拉取新消息
        3) 对新增 user 消息逐条推理并回写 assistant 消息

        返回值：本次处理的 user 消息条数。
        """
        channel = self._resolve_channel(signal.channel)
        last_processed_id = self._last_processed_user_message_id.get(signal.channel, 0)

        messages = channel.list_messages(since_id=last_processed_id)
        pending_user_messages = [
            msg
            for msg in messages
            if msg.role == "user" and msg.message_id > last_processed_id
        ]

        for user_msg in pending_user_messages:
            reply = self._think_for_user_content(user_msg.content)
            channel.send_message(role="assistant", content=reply)
            self._last_processed_user_message_id[signal.channel] = user_msg.message_id

        return len(pending_user_messages)
