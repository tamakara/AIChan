from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from ..router.schemas import AgentInboundMessage
from .outbound_client import OutboundClient

IdleCallback = Callable[[str, "SessionRunner"], Awaitable[None]]


class SessionRunner:
    def __init__(
        self,
        session_id: str,
        agent_id: str,
        outbound_client: OutboundClient,
        debounce_seconds: float,
        post_run_grace_seconds: float,
        max_wait_seconds: float,
        on_idle: IdleCallback,
    ) -> None:
        self._logger = get_logger("session_runner")
        self._session_id = session_id
        self._agent_id = agent_id
        self._outbound_client = outbound_client
        self._debounce_seconds = debounce_seconds
        self._post_run_grace_seconds = post_run_grace_seconds
        self._max_wait_seconds = max_wait_seconds
        self._on_idle = on_idle
        self._pending_messages: list[tuple[int, AgentInboundMessage]] = []
        self._debounce_deadline: float | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._running = False
        self._stopping = False
        self._message_seq = 0
        self._latest_message_seq = 0
        self._reply_cycle_started_at: float | None = None
        self._reply_cycle_deadline_at: float | None = None
        self._lock = asyncio.Lock()

    async def submit_message(self, message: AgentInboundMessage) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._stopping:
                return

            self._message_seq += 1
            message_seq = self._message_seq
            self._latest_message_seq = message_seq
            # 为每条消息打单调序号，后续可用“批次最大序号”判断本轮回复是否已经过时。
            self._pending_messages.append((message_seq, message))
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
                if not self._pending_messages:
                    self._debounce_task = None
                    should_notify_idle = self._is_idle_locked()
                    break

                batched_items = self._pending_messages.copy()
                self._pending_messages.clear()
                self._running = True
                self._debounce_deadline = None
                self._debounce_task = None
                should_notify_idle = False

            await self._run_once(batched_items)
            return

        if should_notify_idle:
            await self._on_idle(self._session_id, self)

    async def _run_once(self, items: list[tuple[int, AgentInboundMessage]]) -> None:
        run_started_at = start_timer()
        messages = [message for _, message in items]
        batch_max_seq = items[-1][0]
        log_info(
            self._logger,
            "hub.session_run_started",
            session_id=self._session_id,
            agent_id=self._agent_id,
            message_count=len(messages),
        )
        try:
            # 回复链路的总等待预算从首次调用 agent 开始，后续重跑不重置预算。
            self._start_reply_cycle_if_needed()
            reply = await self._outbound_client.call_agent(
                session_id=self._session_id,
                agent_id=self._agent_id,
                messages=messages,
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
                if self._pending_messages and not self._stopping:
                    if self._debounce_deadline is None:
                        self._debounce_deadline = (
                            asyncio.get_running_loop().time() + self._debounce_seconds
                        )
                    self._schedule_debounce_locked()
                else:
                    self._reset_reply_cycle()
                    should_notify_idle = self._is_idle_locked()

            if should_notify_idle:
                await self._on_idle(self._session_id, self)

    def _start_reply_cycle_if_needed(self) -> None:
        if self._reply_cycle_started_at is not None:
            return
        now = asyncio.get_running_loop().time()
        self._reply_cycle_started_at = now
        self._reply_cycle_deadline_at = now + self._max_wait_seconds

    def _reset_reply_cycle(self) -> None:
        self._reply_cycle_started_at = None
        self._reply_cycle_deadline_at = None

    async def _decide_reply_delivery(self, *, batch_max_seq: int) -> tuple[bool, str]:
        while True:
            async with self._lock:
                deadline_at = self._reply_cycle_deadline_at
                started_at = self._reply_cycle_started_at
                latest_seq = self._latest_message_seq
            if deadline_at is None or started_at is None:
                return True, "no_cycle_deadline"

            now = asyncio.get_running_loop().time()
            if now >= deadline_at:
                # 触达总等待上限后必须立即发送，避免会话在高频消息下长期无回复。
                log_info(
                    self._logger,
                    "hub.session_reply_forced_send",
                    session_id=self._session_id,
                    agent_id=self._agent_id,
                    elapsed_ms=int((now - started_at) * 1000),
                )
                return True, "max_wait_exceeded"

            if latest_seq > batch_max_seq:
                return False, "new_message_arrived"

            baseline_seq = latest_seq
            wait_seconds = min(self._post_run_grace_seconds, max(0.0, deadline_at - now))
            if wait_seconds <= 0:
                continue

            # 短暂静默窗口用于吸收“刚生成完又补一句”的输入，窗口内有新消息就放弃旧回复。
            await asyncio.sleep(wait_seconds)
            async with self._lock:
                latest_seq_after_wait = self._latest_message_seq
            if latest_seq_after_wait <= baseline_seq:
                return True, "grace_window_passed"

    def _is_idle_locked(self) -> bool:
        if self._running:
            return False
        if self._pending_messages:
            return False
        if self._debounce_task is not None and not self._debounce_task.done():
            return False
        return True
