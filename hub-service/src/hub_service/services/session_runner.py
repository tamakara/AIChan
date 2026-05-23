from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..router.schemas import AgentInboundEvent
from .outbound_client import OutboundClient
from .tag_builder import build_batch_xml

IdleCallback = Callable[[str, "SessionRunner"], Awaitable[None]]


class SessionRunner:
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        outbound_client: OutboundClient,
        debounce_seconds: float,
        on_idle: IdleCallback,
    ) -> None:
        self._logger = get_logger("session_runner")
        self._session_id = session_id
        self._agent_id = agent_id
        self._outbound_client = outbound_client
        self._debounce_seconds = debounce_seconds
        self._on_idle = on_idle
        self._pending_events: list[tuple[int, AgentInboundEvent]] = []
        self._debounce_deadline: float | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._running = False
        self._stopping = False
        self._message_seq = 0
        self._latest_message_seq = 0
        self._reply_cycle_active = False
        self._lock = asyncio.Lock()

    async def submit_message(self, message: AgentInboundEvent) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._stopping:
                return

            self._message_seq += 1
            message_seq = self._message_seq
            self._latest_message_seq = message_seq
            # 为每条消息打单调序号，后续可用“批次最大序号”判断本轮回复是否已经过时。
            self._pending_events.append((message_seq, message))
            self._debounce_deadline = loop.time() + self._debounce_seconds

            if self._running:
                return
            self._schedule_debounce_locked()

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
            name=f"hub-session-runner-{self._session_id}",
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
                    # 这里不直接运行是为了保证“静默窗口”稳定，避免用户连发时频繁触发 agent。
                    continue
                if self._running:
                    self._debounce_task = None
                    should_notify_idle = False
                    break
                if not self._pending_events:
                    self._debounce_task = None
                    should_notify_idle = self._is_idle_locked()
                    break

                batched_items = self._pending_events.copy()
                self._pending_events.clear()
                self._running = True
                self._debounce_deadline = None
                self._debounce_task = None
                should_notify_idle = False

            await self._run_once(batched_items)
            return

        if should_notify_idle:
            await self._on_idle(self._session_id, self)

    async def _run_once(self, items: list[tuple[int, AgentInboundEvent]]) -> None:
        run_started_at = start_timer()
        events = [event for _, event in items]
        message_mode = self._resolve_message_mode()
        batch_xml = build_batch_xml(
            event_xmls=[event.event_xml for event in events],
            batch_type=message_mode,
        )
        batch_max_seq = items[-1][0]
        log_info(
            self._logger,
            "hub.session_run_started",
            session_id=self._session_id,
            agent_id=self._agent_id,
            message_count=len(events),
            message_mode=message_mode,
        )
        try:
            # 标记回复链路已开始，后续因消息更新触发重跑时统一使用 append 语义。
            self._start_reply_cycle_if_needed()
            reply = await self._outbound_client.call_agent(
                session_id=self._session_id,
                agent_id=self._agent_id,
                batch_xml=batch_xml,
            )
            should_send, reason = await self._decide_reply_delivery(batch_max_seq=batch_max_seq)
            if should_send:
                await self._outbound_client.send_reply(session_id=self._session_id, content=reply)
                log_info(
                    self._logger,
                    "hub.session_run_completed",
                    session_id=self._session_id,
                    agent_id=self._agent_id,
                    reply_len=len(reply),
                    elapsed_ms=elapsed_ms(run_started_at),
                )
                self._reset_reply_cycle()
            else:
                log_info(
                    self._logger,
                    "hub.session_reply_discarded",
                    session_id=self._session_id,
                    agent_id=self._agent_id,
                    reason=reason,
                    elapsed_ms=elapsed_ms(run_started_at),
                )
        except Exception:
            log_exception(
                self._logger,
                "hub.session_run_failed",
                session_id=self._session_id,
                agent_id=self._agent_id,
                elapsed_ms=elapsed_ms(run_started_at),
            )
            self._reset_reply_cycle()
        finally:
            should_notify_idle = False
            async with self._lock:
                self._running = False
                if self._pending_events and not self._stopping:
                    # 只要进入重跑，就重新开启完整防抖窗口；避免“运行中早到消息”导致立即重跑。
                    self._debounce_deadline = (
                        asyncio.get_running_loop().time() + self._debounce_seconds
                    )
                    self._schedule_debounce_locked()
                else:
                    self._reset_reply_cycle()
                    should_notify_idle = self._is_idle_locked()

            if should_notify_idle:
                await self._on_idle(self._session_id, self)

    def _resolve_message_mode(self) -> Literal["start", "append"]:
        # 首轮输入使用 start，重跑输入使用 append，让模型能区分“新轮次”与“补充消息”。
        if not self._reply_cycle_active:
            return "start"
        return "append"

    def _start_reply_cycle_if_needed(self) -> None:
        if self._reply_cycle_active:
            return
        self._reply_cycle_active = True

    def _reset_reply_cycle(self) -> None:
        self._reply_cycle_active = False

    async def _decide_reply_delivery(self, *, batch_max_seq: int) -> tuple[bool, str]:
        async with self._lock:
            latest_seq = self._latest_message_seq

        # 已有更新消息就丢弃当前回复重跑；无更新就立即发送。
        if latest_seq > batch_max_seq:
            return False, "new_message_arrived"
        return True, "no_new_message"

    def _is_idle_locked(self) -> bool:
        if self._running:
            return False
        if self._pending_events:
            return False
        if self._debounce_task is not None and not self._debounce_task.done():
            return False
        return True
