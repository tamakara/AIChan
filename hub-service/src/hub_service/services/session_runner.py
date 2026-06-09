from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..router.schemas import AgentInboundEvent
from .message_xml import FileUrlResolverProtocol, InputMediaStorageProtocol, onebot_private_events_to_input_xml
from .outbound_client import OutboundClient

IdleCallback = Callable[[str, "SessionRunner"], Awaitable[None]]


class SessionRunner:
    """单个会话的运行器 — 防抖 + agent 调用 + 回复发送。"""

    def __init__(
        self,
        session_key: str,
        agent_session_id: str,
        outbound_client: OutboundClient,
        media_storage: InputMediaStorageProtocol | None,
        file_resolver: FileUrlResolverProtocol | None,
        debounce_seconds: float,
        on_idle: IdleCallback,
    ) -> None:
        self._logger = get_logger("session_runner")
        self._session_key = session_key
        self._agent_session_id = agent_session_id
        self._outbound_client = outbound_client
        self._media_storage = media_storage
        self._file_resolver = file_resolver
        self._debounce_seconds = debounce_seconds
        self._on_idle = on_idle
        self._pending_events: list[AgentInboundEvent] = []
        self._debounce_deadline: float | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._running = False
        self._stopping = False
        self._lock = asyncio.Lock()

    @property
    def session_key(self) -> str:
        return self._session_key

    async def submit_message(self, message: AgentInboundEvent) -> None:
        loop = asyncio.get_running_loop()

        should_queue_to_agent = False
        async with self._lock:
            if self._stopping:
                return
            if self._running:
                should_queue_to_agent = True
            else:
                self._pending_events.append(message)
                self._debounce_deadline = loop.time() + self._debounce_seconds
                self._schedule_debounce_locked()

        if should_queue_to_agent:
            input_xml = await onebot_private_events_to_input_xml(
                [message.event],
                media_storage=self._media_storage,
                file_resolver=self._file_resolver,
            )
            await self._outbound_client.queue_session_message(
                self._agent_session_id,
                input_xml,
            )

    async def shutdown(self) -> None:
        self._stopping = True
        async with self._lock:
            task = self._debounce_task
        if task is None or task.done():
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def is_idle(self) -> bool:
        async with self._lock:
            return self._is_idle_locked()

    def _schedule_debounce_locked(self) -> None:
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(
            self._debounce_then_run(),
            name=f"hub-session-runner-{self._session_key}",
        )

    async def _debounce_then_run(self) -> None:
        should_notify_idle = False
        while not self._stopping:
            async with self._lock:
                deadline = self._debounce_deadline
                if deadline is None:
                    self._debounce_task = None
                    should_notify_idle = self._is_idle_locked()
                    break
                sleep_seconds = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.sleep(sleep_seconds)

            async with self._lock:
                now = asyncio.get_running_loop().time()
                if self._debounce_deadline is None:
                    self._debounce_task = None
                    should_notify_idle = self._is_idle_locked()
                    break
                if now < self._debounce_deadline:
                    continue
                if not self._pending_events:
                    self._debounce_task = None
                    should_notify_idle = self._is_idle_locked()
                    break

                batched_events = self._pending_events.copy()
                self._pending_events.clear()
                self._running = True
                self._debounce_deadline = None
                self._debounce_task = None
                should_notify_idle = False

            await self._run_once(batched_events)
            return

        if should_notify_idle:
            await self._on_idle(self._session_key, self)

    async def _run_once(self, events: list[AgentInboundEvent]) -> None:
        run_started_at = start_timer()
        raw_events = [e.event for e in events]
        input_xml = await onebot_private_events_to_input_xml(
            raw_events,
            media_storage=self._media_storage,
            file_resolver=self._file_resolver,
        )

        log_info(
            self._logger,
            "hub.session_run_started",
            session_key=self._session_key,
            agent_id=self._agent_session_id,
            event_count=len(events),
        )
        try:
            reply = await self._outbound_client.call_session(
                hub_session_key=self._session_key,
                agent_session_id=self._agent_session_id,
                input_xml=input_xml,
            )
            await self._outbound_client.send_reply(
                session_key=self._session_key,
                output_xml=reply.output_xml,
            )
            log_info(
                self._logger,
                "hub.session_run_completed",
                session_key=self._session_key,
                agent_id=self._agent_session_id,
                reply_len=len(reply.output_xml),
                elapsed_ms=elapsed_ms(run_started_at),
            )
        except Exception:
            log_exception(
                self._logger,
                "hub.session_run_failed",
                session_key=self._session_key,
                agent_id=self._agent_session_id,
                elapsed_ms=elapsed_ms(run_started_at),
            )
        finally:
            should_notify_idle = False
            async with self._lock:
                self._running = False
                if self._pending_events and not self._stopping:
                    self._debounce_deadline = (
                        asyncio.get_running_loop().time() + self._debounce_seconds
                    )
                    self._schedule_debounce_locked()
                else:
                    should_notify_idle = self._is_idle_locked()

            if should_notify_idle:
                await self._on_idle(self._session_key, self)

    def _is_idle_locked(self) -> bool:
        if self._running:
            return False
        if self._pending_events:
            return False
        if self._debounce_task is not None and not self._debounce_task.done():
            return False
        return True
