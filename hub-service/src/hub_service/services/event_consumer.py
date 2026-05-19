from __future__ import annotations

import asyncio

from pydantic import ValidationError

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .redis_stream import HubRedisStream
from .session_coordinator import SessionCoordinator
from .stream_models import EventStreamMessage


class EventConsumerWorker:
    def __init__(
        self,
        redis_stream: HubRedisStream,
        session_coordinator: SessionCoordinator,
    ) -> None:
        self._logger = get_logger("event_consumer")
        self._redis_stream = redis_stream
        self._session_coordinator = session_coordinator
        self._stopping = False
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run_loop(), name="hub-event-consumer")
        log_info(self._logger, "hub.consumer_started")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            log_info(self._logger, "hub.consumer_stopped")
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log_info(self._logger, "hub.consumer_stopped")

    async def _run_loop(self) -> None:
        while not self._stopping:
            pending = await self._redis_stream.read_pending_events(count=20)
            if pending:
                await self._handle_batch(pending)
                continue

            fresh = await self._redis_stream.read_new_events(count=20)
            if fresh:
                await self._handle_batch(fresh)

    async def _handle_batch(self, rows: list[tuple[str, dict[str, str]]]) -> None:
        for message_id, fields in rows:
            handled_started_at = start_timer()
            try:
                event = EventStreamMessage.from_stream_fields(fields)
                if event.message_type != "private":
                    await self._redis_stream.ack_event(message_id)
                    log_info(
                        self._logger,
                        "hub.event_skipped",
                        message_id=message_id,
                        message_type=event.message_type,
                    )
                    continue
                await self._session_coordinator.submit_event(event)
                await self._redis_stream.ack_event(message_id)
                log_info(
                    self._logger,
                    "hub.event_submitted",
                    message_id=message_id,
                    event_id=event.event_id,
                    session_id=event.session_id,
                )
            except ValidationError:
                # 非法消息直接丢弃，避免单条坏数据长期占用消费游标。
                log_exception(
                    self._logger,
                    "hub.event_dropped",
                    message_id=message_id,
                    reason="invalid_stream_message",
                )
                await self._redis_stream.ack_event(message_id)
            except Exception:
                # 运行期异常按未 ACK 保留在 PEL，后续自动重试保证至少一次消费。
                log_exception(
                    self._logger,
                    "hub.event_retry",
                    message_id=message_id,
                    elapsed_ms=elapsed_ms(handled_started_at),
                )
                await asyncio.sleep(1)
