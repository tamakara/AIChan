from __future__ import annotations

import time
from typing import Any, Callable

import httpx

from agent.agent import Agent
from core.entities import AgentSignal, ChannelMessage
from core.logger import logger
from mcp_hub import MCPManager


class SignalProcessor:
    """
    信号处理器：根据通道信号拉取消息并驱动 Agent 推理。

    当前版本职责：
    1. 从通道配置解析读写地址；
    2. 拉取通道消息并拆分 old/new 上下文；
    3. 从 MCPHub 获取动态工具快照并构建 Agent；
    4. 执行推理并回写 assistant 消息。
    """

    def __init__(
        self,
        llm_factory: Callable[[], Any],
        channel_config_registry: dict[str, Any],
        mcp_manager: MCPManager,
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self._llm_factory = llm_factory
        self._channel_config_registry = channel_config_registry
        self._mcp_manager = mcp_manager
        self._request_timeout_seconds = request_timeout_seconds
        # 每个通道最后处理到的 user 消息 ID。
        self._last_processed_user_message_id: dict[str, int] = {}

    def _resolve_channel_base_url(self, channel_name: str) -> str:
        """根据信号中的通道名定位通道配置。"""
        config = self._channel_config_registry.get(channel_name)
        if config is None:
            raise ValueError(f"未找到网关配置: {channel_name}")

        gateway_type = self._read_config_value(config, "gateway_type")
        if gateway_type != "channel":
            raise ValueError(f"网关不是 channel 类型: {channel_name}")

        base_url = self._read_config_value(config, "base_url")
        if not base_url:
            raise ValueError(f"网关 base_url 缺失: {channel_name}")
        return base_url

    @staticmethod
    def _read_config_value(config: Any, field: str) -> str:
        if isinstance(config, dict):
            return str(config.get(field, "")).strip()
        return str(getattr(config, field, "")).strip()

    @staticmethod
    def _split_old_new_messages(
        all_messages: list[ChannelMessage],
        last_processed_id: int,
    ) -> tuple[list[ChannelMessage], list[ChannelMessage]]:
        """按 message_id 将消息拆分为历史集合与新增集合。"""
        ordered_messages = sorted(all_messages, key=lambda message: message.message_id)
        old_messages = [msg for msg in ordered_messages if msg.message_id <= last_processed_id]
        new_messages = [msg for msg in ordered_messages if msg.message_id > last_processed_id]
        return old_messages, new_messages

    def _list_channel_messages(self, channel_name: str, base_url: str) -> list[ChannelMessage]:
        """从通道网关拉取完整消息列表并映射为内部消息格式。"""
        try:
            with httpx.Client(timeout=self._request_timeout_seconds) as client:
                response = client.get(f"{base_url}/v1/messages", params={"after_id": 0})
                response.raise_for_status()
                raw_messages = response.json()
        except Exception as exc:
            raise RuntimeError(f"通道拉取消息失败（{channel_name}）：{exc}") from exc

        if not isinstance(raw_messages, list):
            raise RuntimeError(f"通道返回的消息结构非法（{channel_name}）：不是列表")

        parsed_messages: list[ChannelMessage] = []
        for raw_item in raw_messages:
            if not isinstance(raw_item, dict):
                logger.warning("⚠️ [Signal] 跳过非法消息项（非对象），channel='{}'", channel_name)
                continue

            raw_id = raw_item.get("id")
            sender = raw_item.get("sender")
            text = raw_item.get("text")

            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                logger.warning("⚠️ [Signal] 跳过非法消息 id，channel='{}'，raw='{}'", channel_name, raw_id)
                continue

            if not isinstance(text, str):
                logger.warning("⚠️ [Signal] 跳过非法消息 text，channel='{}'", channel_name)
                continue

            parsed_messages.append(
                ChannelMessage(
                    message_id=message_id,
                    channel=channel_name,
                    role=self._map_sender_to_role(sender),
                    content=text,
                )
            )

        return sorted(parsed_messages, key=lambda message: message.message_id)

    @staticmethod
    def _map_sender_to_role(sender: object) -> str:
        """将网关 sender 字段映射到内部消息角色。"""
        if sender == "user":
            return "user"
        if sender in {"assistant", "ai", "system"}:
            return "assistant"
        return "assistant"

    def _send_assistant_message(
        self,
        channel_name: str,
        base_url: str,
        content: str,
    ) -> ChannelMessage:
        """向通道网关写回 assistant 消息。"""
        payload = {"sender": "ai", "text": content}
        try:
            with httpx.Client(timeout=self._request_timeout_seconds) as client:
                response = client.post(f"{base_url}/v1/messages", json=payload)
                response.raise_for_status()
                raw_message = response.json()
        except Exception as exc:
            raise RuntimeError(f"通道发送消息失败（{channel_name}）：{exc}") from exc

        if not isinstance(raw_message, dict):
            raise RuntimeError(f"通道发送返回非法结构（{channel_name}）：不是对象")

        raw_id = raw_message.get("id")
        text = raw_message.get("text", content)
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"通道返回非法 message id（{channel_name}）：{raw_id}") from exc

        if not isinstance(text, str):
            text = content

        return ChannelMessage(
            message_id=message_id,
            channel=channel_name,
            role="assistant",
            content=text,
        )

    def process_signal(
        self,
        signal: AgentSignal,
        signal_id: str | None = None,
    ) -> int:
        """
        处理一条通道信号。

        执行步骤：
        1. 根据 signal.channel 解析通道配置；
        2. 拉取通道消息并拆分 old/new；
        3. 从 MCPHub 拉取最新工具快照并重建 Agent；
        4. 推理并回写 assistant 消息。

        返回值：本次处理的新 user 消息条数。
        """
        trace_prefix = signal_id or f"{signal.channel}#manual"
        started_at = time.perf_counter()
        logger.info(
            "🚀 [Signal] signal_id={} 开始处理通道 '{}'",
            trace_prefix,
            signal.channel,
        )

        base_url = self._resolve_channel_base_url(signal.channel)
        last_processed_id = self._last_processed_user_message_id.get(signal.channel, 0)
        all_messages = self._list_channel_messages(channel_name=signal.channel, base_url=base_url)
        old_messages, new_messages = self._split_old_new_messages(
            all_messages=all_messages,
            last_processed_id=last_processed_id,
        )
        pending_user_messages = [message for message in new_messages if message.role == "user"]
        latest_message_id = max((message.message_id for message in all_messages), default=0)

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

        # 每次信号处理都刷新一次工具快照，确保 Agent 使用最新外设能力。
        dynamic_tools = self._mcp_manager.get_all_tools_sync(refresh=True)
        logger.info(
            "🧰 [Signal] signal_id={} MCP 工具数量={}",
            trace_prefix,
            len(dynamic_tools),
        )
        agent = Agent(llm_client=self._llm_factory(), tools=dynamic_tools)

        total_pending = len(pending_user_messages)
        msg_trace_id = (
            f"{trace_prefix}:batch_user#{pending_user_messages[0].message_id}"
            f"-{pending_user_messages[-1].message_id}:count={total_pending}"
        )
        reply = agent.think(
            old_messages=old_messages,
            new_messages=new_messages,
            trace_id=msg_trace_id,
        )

        sent_message = self._send_assistant_message(
            channel_name=signal.channel,
            base_url=base_url,
            content=reply,
        )

        latest_user_message_id = max(message.message_id for message in pending_user_messages)
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
