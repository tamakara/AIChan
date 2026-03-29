from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import httpx
from pydantic import BaseModel, create_model
from langchain_core.tools import StructuredTool

from agent.agent import Agent
from core.entities import AgentSignal, ChannelMessage
from core.logger import logger


class SignalProcessor:
    """
    信号处理器：根据通道信号拉取消息并驱动 Agent 推理。

    与旧版差异：
    1. 不再依赖旧静态插件体系；
    2. 通道读写能力来自 Registry 网关配置；
    3. 每次处理信号前，按最新工具快照重建 Agent。
    """

    def __init__(
        self,
        llm_factory: Callable[[], Any],
        gateway_config_registry: dict[str, Any],
        gateway_tools_registry: dict[str, dict[str, Any]],
        request_timeout_seconds: float = 10.0,
    ) -> None:
        self._llm_factory = llm_factory
        self._gateway_config_registry = gateway_config_registry
        self._gateway_tools_registry = gateway_tools_registry
        self._request_timeout_seconds = request_timeout_seconds
        # 每个通道最后处理到的 user 消息 ID。
        self._last_processed_user_message_id: dict[str, int] = {}

    def _resolve_channel_base_url(self, channel_name: str) -> str:
        """根据信号中的通道名定位 Registry 网关配置。"""
        config = self._gateway_config_registry.get(channel_name)
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

    def _build_dynamic_tools(self) -> list[StructuredTool]:
        """
        从注册中心工具快照构建可绑定给 Agent 的工具集合。

        注意：
        - 每次信号处理都会调用该方法；
        - 读取时使用浅拷贝，避免并发写入导致遍历异常。
        """
        dynamic_tools: list[StructuredTool] = []
        for gateway_name, gateway_meta in list(self._gateway_tools_registry.items()):
            if not isinstance(gateway_meta, dict):
                continue

            raw_tools = gateway_meta.get("tools")
            if not isinstance(raw_tools, dict):
                continue

            for _, raw_tool_spec in list(raw_tools.items()):
                if not isinstance(raw_tool_spec, dict):
                    continue
                try:
                    dynamic_tools.append(self._build_structured_tool(raw_tool_spec))
                except Exception as exc:
                    logger.error(
                        "❌ [Signal] 动态工具构建失败，gateway='{}'，error='{}'",
                        gateway_name,
                        exc,
                    )
        return dynamic_tools

    def _build_structured_tool(self, tool_spec: dict[str, Any]) -> StructuredTool:
        """将工具元数据转换为 StructuredTool。"""
        tool_name = str(tool_spec.get("name", "")).strip()
        if not tool_name:
            raise ValueError("tool name 不能为空")

        description = str(tool_spec.get("description", "动态网关工具")).strip()
        method = str(tool_spec.get("method", "POST")).strip().upper()
        url = str(tool_spec.get("url", "")).strip()
        if not url:
            raise ValueError(f"工具 URL 为空：{tool_name}")

        input_schema = tool_spec.get("input_schema")
        args_schema = self._build_args_schema(tool_name=tool_name, input_schema=input_schema)
        executor = self._build_tool_executor(tool_name=tool_name, method=method, url=url)
        return StructuredTool.from_function(
            name=tool_name,
            description=description,
            args_schema=args_schema,
            func=executor,
        )

    def _build_args_schema(
        self,
        tool_name: str,
        input_schema: Any,
    ) -> type[BaseModel]:
        """根据 OpenAPI 入参 schema 动态创建工具参数模型。"""
        if not isinstance(input_schema, dict):
            return self._create_empty_args_model(tool_name)

        properties = input_schema.get("properties")
        if not isinstance(properties, dict):
            return self._create_empty_args_model(tool_name)

        required_fields = input_schema.get("required")
        required_set = set(required_fields) if isinstance(required_fields, list) else set()
        model_fields: dict[str, tuple[Any, Any]] = {}

        for raw_field_name, raw_field_schema in properties.items():
            field_name = str(raw_field_name).strip()
            if not field_name:
                continue
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", field_name):
                # 非法 Python 字段名直接跳过，避免影响模型构造。
                logger.warning("⚠️ [Signal] 跳过非法工具字段名：{}", field_name)
                continue

            python_type = self._json_schema_type_to_python(raw_field_schema)
            if field_name in required_set:
                model_fields[field_name] = (python_type, ...)
            else:
                model_fields[field_name] = (python_type | None, None)

        if not model_fields:
            return self._create_empty_args_model(tool_name)

        model_name = self._to_model_name(tool_name)
        return create_model(model_name, **model_fields)

    @staticmethod
    def _json_schema_type_to_python(raw_field_schema: Any) -> Any:
        """将 JSON Schema type 映射为 Python 类型。"""
        if not isinstance(raw_field_schema, dict):
            return Any
        field_type = raw_field_schema.get("type")
        if field_type == "string":
            return str
        if field_type == "integer":
            return int
        if field_type == "number":
            return float
        if field_type == "boolean":
            return bool
        if field_type == "array":
            return list[Any]
        if field_type == "object":
            return dict[str, Any]
        return Any

    @staticmethod
    def _to_model_name(tool_name: str) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", tool_name).strip("_")
        if not sanitized:
            sanitized = "DynamicTool"
        return f"{sanitized.title().replace('_', '')}Args"

    @staticmethod
    def _create_empty_args_model(tool_name: str) -> type[BaseModel]:
        model_name = f"{SignalProcessor._to_model_name(tool_name)}Empty"
        return create_model(model_name)

    def _build_tool_executor(
        self,
        tool_name: str,
        method: str,
        url: str,
    ) -> Callable[..., str]:
        """构造动态工具执行函数：将工具调用转发到网关 HTTP 接口。"""

        def _executor(**kwargs: Any) -> str:
            started_at = time.perf_counter()
            logger.info(
                "🛠 [DynamicTool] 调用工具，name='{}'，method='{}'，url='{}'",
                tool_name,
                method,
                url,
            )
            try:
                with httpx.Client(timeout=self._request_timeout_seconds) as client:
                    if method == "GET":
                        response = client.request(method, url, params=kwargs or None)
                    else:
                        response = client.request(method, url, json=kwargs or None)
                    response.raise_for_status()
            except Exception as exc:
                raise RuntimeError(f"工具调用失败（{tool_name}）：{exc}") from exc

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info("✅ [DynamicTool] 调用完成，name='{}'，耗时={}ms", tool_name, elapsed_ms)

            try:
                payload = response.json()
            except ValueError:
                payload = {"raw_text": response.text}
            return json.dumps(payload, ensure_ascii=False)

        return _executor

    def process_signal(
        self,
        signal: AgentSignal,
        signal_id: str | None = None,
    ) -> int:
        """
        处理一条通道信号。

        执行步骤：
        1. 根据 signal.channel 解析 Registry 通道配置；
        2. 拉取通道消息并拆分 old/new；
        3. 动态构建工具并重建 Agent；
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

        dynamic_tools = self._build_dynamic_tools()
        logger.info(
            "🧰 [Signal] signal_id={} 动态工具数量={}",
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
