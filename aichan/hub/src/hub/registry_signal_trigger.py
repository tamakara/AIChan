from __future__ import annotations

import asyncio
from typing import Any

from core.entities import AgentSignal
from core.logger import logger
from hub.signal_hub import SignalHub


class RegistrySignalTrigger:
    """
    注册中心事件触发器。

    职责边界：
    1. 从 `global_event_bus` 持续消费事件；
    2. 仅对 `channel` 类型网关的 `user` 新消息触发信号；
    3. 做 message_id 去重，避免 SSE 重连导致重复推理。
    """

    def __init__(
        self,
        signal_hub: SignalHub,
        global_event_bus: asyncio.Queue[dict[str, Any]],
        gateway_config_registry: dict[str, Any],
    ) -> None:
        self._signal_hub = signal_hub
        self._global_event_bus = global_event_bus
        self._gateway_config_registry = gateway_config_registry
        self._latest_user_message_id: dict[str, int] = {}
        self._worker_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """启动后台触发任务。"""
        if self._worker_task is not None and not self._worker_task.done():
            logger.warning("♻️ [SignalTrigger] 触发器已在运行，忽略重复启动")
            return

        self._worker_task = asyncio.create_task(
            self._run_loop(),
            name="registry-signal-trigger",
        )
        logger.info("🟢 [SignalTrigger] 注册中心事件触发器已启动")

    async def stop(self) -> None:
        """停止后台触发任务并等待退出。"""
        task = self._worker_task
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🛑 [SignalTrigger] 触发器任务已取消")
        finally:
            self._worker_task = None

    async def _run_loop(self) -> None:
        """主循环：持续消费事件总线并触发 SignalHub 入队。"""
        try:
            while True:
                event_record = await self._global_event_bus.get()
                try:
                    self._handle_event(event_record)
                except Exception as exc:
                    logger.error(
                        "❌ [SignalTrigger] 处理事件失败：{}: {}",
                        exc.__class__.__name__,
                        exc,
                    )
                finally:
                    self._global_event_bus.task_done()
        except asyncio.CancelledError:
            logger.info("🛑 [SignalTrigger] 主循环停止")
            raise

    def _handle_event(self, event_record: dict[str, Any]) -> None:
        gateway_name = str(event_record.get("gateway", "")).strip()
        if not gateway_name:
            logger.warning("⚠️ [SignalTrigger] 事件缺少 gateway 字段，已忽略")
            return

        gateway_type = self._get_gateway_type(gateway_name)
        if gateway_type != "channel":
            # tool 网关不会触发信号，仅保留工具映射能力。
            return

        payload = event_record.get("payload")
        if not isinstance(payload, dict):
            logger.warning("⚠️ [SignalTrigger] 事件 payload 非对象，gateway='{}'", gateway_name)
            return

        sender = payload.get("sender")
        if sender != "user":
            return

        raw_message_id = payload.get("id")
        try:
            message_id = int(raw_message_id)
        except (TypeError, ValueError):
            logger.warning(
                "⚠️ [SignalTrigger] 非法 message id，gateway='{}'，raw='{}'",
                gateway_name,
                raw_message_id,
            )
            return

        last_seen_message_id = self._latest_user_message_id.get(gateway_name, 0)
        if message_id <= last_seen_message_id:
            return
        self._latest_user_message_id[gateway_name] = message_id

        try:
            self._signal_hub.push_signal(AgentSignal(channel=gateway_name))
            logger.info(
                "🔔 [SignalTrigger] 触发新信号，gateway='{}'，message_id={}",
                gateway_name,
                message_id,
            )
        except RuntimeError as exc:
            logger.error(
                "❌ [SignalTrigger] SignalHub 未就绪，gateway='{}'，error='{}'",
                gateway_name,
                exc,
            )

    def _get_gateway_type(self, gateway_name: str) -> str:
        """
        读取网关类型。

        兼容 dict/dataclass 两种配置对象形态，避免触发器对具体实现耦合。
        """
        config = self._gateway_config_registry.get(gateway_name)
        if config is None:
            return ""
        if isinstance(config, dict):
            return str(config.get("gateway_type", "")).strip()
        return str(getattr(config, "gateway_type", "")).strip()

