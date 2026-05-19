from __future__ import annotations

import asyncio

from pydantic import ValidationError

from ..logger import elapsed_ms, get_logger, log_exception, log_info, log_warning, start_timer
from .channel_service import AdapterService
from .connection_state import NapcatConnectionState
from .errors import NapcatDownstreamError
from .napcat_ws_gateway import NapcatWsGateway
from .redis_stream import AdapterRedisStream
from .stream_models import ActionStreamMessage


class ActionConsumerWorker:
    def __init__(
        self,
        redis_stream: AdapterRedisStream,
        napcat_gateway: NapcatWsGateway,
        napcat_connection_state: NapcatConnectionState,
        channel_service: AdapterService,
    ) -> None:
        self._logger = get_logger("action_consumer")
        self._redis_stream = redis_stream
        self._napcat_gateway = napcat_gateway
        self._napcat_connection_state = napcat_connection_state
        self._channel_service = channel_service
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        self._stopping = False
        self._task = asyncio.create_task(self._run_loop(), name="adapter-action-consumer")
        log_info(self._logger, "channel.action_consumer_started")

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            log_info(self._logger, "channel.action_consumer_stopped")
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        log_info(self._logger, "channel.action_consumer_stopped")

    async def _run_loop(self) -> None:
        while not self._stopping:
            pending = await self._redis_stream.read_pending_actions(count=10)
            if pending:
                await self._handle_batch(pending)
                continue

            fresh = await self._redis_stream.read_new_actions(count=10)
            if fresh:
                await self._handle_batch(fresh)

    async def _handle_batch(self, messages: list[tuple[str, dict[str, str]]]) -> None:
        for message_id, fields in messages:
            handled_started_at = start_timer()
            try:
                action = ActionStreamMessage.from_stream_fields(fields)
                await self._handle_action(action)
            except ValidationError:
                # 非法消息直接 ACK，避免毒消息卡死整个消费分组。
                log_exception(
                    self._logger,
                    "channel.action_dropped",
                    message_id=message_id,
                    reason="invalid_stream_message",
                )
                await self._redis_stream.ack_action(message_id)
            except ValueError:
                # session_id 或动作参数不合法属于不可恢复输入错误，直接丢弃。
                log_exception(
                    self._logger,
                    "channel.action_dropped",
                    message_id=message_id,
                    reason="invalid_action_payload",
                )
                await self._redis_stream.ack_action(message_id)
            except Exception:
                # 运行期故障按未 ACK 留在 PEL，下一轮优先重试，保证至少一次投递。
                log_exception(
                    self._logger,
                    "channel.action_retry",
                    message_id=message_id,
                    elapsed_ms=elapsed_ms(handled_started_at),
                )
                await asyncio.sleep(1)
                continue
            await self._redis_stream.ack_action(message_id)
            log_info(
                self._logger,
                "channel.action_handled",
                session_id=action.session_id,
                action_type=action.action_type,
                status="ok",
                elapsed_ms=elapsed_ms(handled_started_at),
            )

    async def _handle_action(self, action: ActionStreamMessage) -> None:
        if action.action_type != "send_message":
            log_warning(
                self._logger,
                "channel.action_skipped",
                action_type=action.action_type,
                reason="unknown_action_type",
            )
            return

        websocket = self._napcat_connection_state.get()
        if websocket is None:
            raise RuntimeError("onebot reverse ws is not connected")

        outbound_action = self._channel_service.build_send_message_action(
            session_id=action.session_id,
            content=action.payload.content,
        )
        result = await self._napcat_gateway.send_action(
            websocket=websocket,
            action=outbound_action.action,
            params=outbound_action.params,
        )
        if result.get("status") != "ok":
            raise NapcatDownstreamError(f"onebot action failed: {result}")
