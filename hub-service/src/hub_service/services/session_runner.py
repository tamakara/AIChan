from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .outbound_client import OutboundClient

IdleCallback = Callable[[str, "SessionRunner"], Awaitable[None]]


class SessionRunner:
    def __init__(
        self,
        session_id: str,
        outbound_client: OutboundClient,
        debounce_seconds: float,
        on_idle: IdleCallback,
    ) -> None:
        self._logger = get_logger("session_runner")
        self._session_id = session_id
        self._outbound_client = outbound_client
        self._debounce_seconds = debounce_seconds
        self._on_idle = on_idle
        self._pending_messages: list[str] = []
        self._debounce_deadline: float | None = None
        self._debounce_task: asyncio.Task[None] | None = None
        self._running = False
        self._stopping = False
        self._lock = asyncio.Lock()

    async def submit_message(self, content: str) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._stopping:
                return

            self._pending_messages.append(content)
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

                merged_message = "\n".join(self._pending_messages)
                self._pending_messages.clear()
                self._running = True
                self._debounce_deadline = None
                self._debounce_task = None
                should_notify_idle = False

            await self._run_once(merged_message)
            return

        if should_notify_idle:
            await self._on_idle(self._session_id, self)

    async def _run_once(self, user_message: str) -> None:
        run_started_at = start_timer()
        log_info(
            self._logger,
            "hub.session_run_started",
            session_id=self._session_id,
            user_message_len=len(user_message),
        )
        try:
            reply = await self._outbound_client.call_agent(
                session_id=self._session_id,
                user_message=user_message,
            )
            await self._outbound_client.send_reply(session_id=self._session_id, content=reply)
            log_info(
                self._logger,
                "hub.session_run_completed",
                session_id=self._session_id,
                reply_len=len(reply),
                elapsed_ms=elapsed_ms(run_started_at),
            )
        except Exception:
            log_exception(
                self._logger,
                "hub.session_run_failed",
                session_id=self._session_id,
                elapsed_ms=elapsed_ms(run_started_at),
            )
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
                    should_notify_idle = self._is_idle_locked()

            if should_notify_idle:
                await self._on_idle(self._session_id, self)

    def _is_idle_locked(self) -> bool:
        if self._running:
            return False
        if self._pending_messages:
            return False
        if self._debounce_task is not None and not self._debounce_task.done():
            return False
        return True
