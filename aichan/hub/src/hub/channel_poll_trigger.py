from __future__ import annotations

import asyncio
from typing import Any

import httpx

from core.entities import AgentSignal
from core.logger import logger
from hub.signal_hub import SignalHub


class ChannelPollTrigger:
    """
    通道轮询触发器。

    在无 Registry 的模式下，通过轮询各通道 `/v1/messages` 检测新增 user 消息，
    并将对应 `AgentSignal` 推送到 `SignalHub`。
    """

    def __init__(
        self,
        signal_hub: SignalHub,
        channel_config_registry: dict[str, Any],
        poll_interval_seconds: float = 1.0,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        self._signal_hub = signal_hub
        self._channel_config_registry = channel_config_registry
        self._poll_interval_seconds = poll_interval_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._latest_user_message_id: dict[str, int] = {}
        self._worker_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        """启动后台轮询任务。"""
        if self._worker_task is not None and not self._worker_task.done():
            logger.warning("♻️ [ChannelTrigger] 触发器已在运行，忽略重复启动")
            return

        self._worker_task = asyncio.create_task(
            self._run_loop(),
            name="channel-poll-trigger",
        )
        logger.info("🟢 [ChannelTrigger] 通道轮询触发器已启动")

    async def stop(self) -> None:
        """停止后台轮询任务并等待退出。"""
        task = self._worker_task
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🛑 [ChannelTrigger] 触发器任务已取消")
        finally:
            self._worker_task = None

    async def _run_loop(self) -> None:
        try:
            while True:
                await self._poll_all_channels()
                await asyncio.sleep(self._poll_interval_seconds)
        except asyncio.CancelledError:
            logger.info("🛑 [ChannelTrigger] 主循环停止")
            raise

    async def _poll_all_channels(self) -> None:
        for channel_name, config in list(self._channel_config_registry.items()):
            try:
                await self._poll_single_channel(channel_name=channel_name, config=config)
            except Exception as exc:
                logger.error(
                    "❌ [ChannelTrigger] 轮询失败，channel='{}'，error='{}: {}'",
                    channel_name,
                    exc.__class__.__name__,
                    exc,
                )

    async def _poll_single_channel(self, channel_name: str, config: Any) -> None:
        gateway_type = self._read_config_value(config=config, field="gateway_type")
        if gateway_type != "channel":
            return

        base_url = self._read_config_value(config=config, field="base_url")
        if not base_url:
            logger.warning("⚠️ [ChannelTrigger] 通道缺少 base_url，channel='{}'", channel_name)
            return

        last_seen = self._latest_user_message_id.get(channel_name, 0)
        payload = await self._fetch_messages(base_url=base_url, after_id=last_seen)
        if not payload:
            return

        user_message_ids: list[int] = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            raw_id = item.get("id")
            sender = item.get("sender")
            try:
                message_id = int(raw_id)
            except (TypeError, ValueError):
                continue

            if sender != "user":
                continue
            if message_id <= last_seen:
                continue
            user_message_ids.append(message_id)

        if not user_message_ids:
            return

        latest_user_id = max(user_message_ids)
        self._latest_user_message_id[channel_name] = latest_user_id

        try:
            self._signal_hub.push_signal(AgentSignal(channel=channel_name))
            logger.info(
                "🔔 [ChannelTrigger] 检测到新 user 消息，channel='{}'，count={}，latest_id={}",
                channel_name,
                len(user_message_ids),
                latest_user_id,
            )
        except RuntimeError as exc:
            logger.error(
                "❌ [ChannelTrigger] SignalHub 未就绪，channel='{}'，error='{}'",
                channel_name,
                exc,
            )

    async def _fetch_messages(self, base_url: str, after_id: int) -> list[dict[str, Any]]:
        url = f"{base_url}/v1/messages"
        try:
            async with httpx.AsyncClient(timeout=self._request_timeout_seconds) as client:
                response = await client.get(url, params={"after_id": after_id})
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning(
                "⚠️ [ChannelTrigger] 拉取消息失败，url='{}'，after_id={}，error='{}: {}'",
                url,
                after_id,
                exc.__class__.__name__,
                exc,
            )
            return []

        if not isinstance(payload, list):
            logger.warning("⚠️ [ChannelTrigger] 消息响应结构非法，url='{}'", url)
            return []
        return payload

    @staticmethod
    def _read_config_value(config: Any, field: str) -> str:
        if isinstance(config, dict):
            return str(config.get(field, "")).strip()
        return str(getattr(config, field, "")).strip()
