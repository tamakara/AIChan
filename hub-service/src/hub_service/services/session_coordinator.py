from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .outbound_client import OutboundClient
from .stream_models import EventStreamMessage


@dataclass
class SessionState:
    running: bool = False
    pending_messages: list[str] = field(default_factory=list)
    debounce_deadline: float | None = None
    debounce_task: asyncio.Task[None] | None = None


class SessionCoordinator:
    def __init__(
        self,
        outbound_client: OutboundClient,
        debounce_seconds: float,
    ) -> None:
        self._logger = get_logger("session_coordinator")
        self._outbound_client = outbound_client
        self._debounce_seconds = debounce_seconds
        self._states: dict[str, SessionState] = {}
        self._lock = asyncio.Lock()
        self._stopping = False

    async def submit_event(self, event: EventStreamMessage) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            state = self._states.setdefault(event.session_id, SessionState())
            state.pending_messages.append(event.content)
            state.debounce_deadline = loop.time() + self._debounce_seconds

            if state.running:
                return
            self._schedule_debounce_locked(event.session_id, state)

    async def shutdown(self) -> None:
        self._stopping = True
        async with self._lock:
            tasks = [
                state.debounce_task
                for state in self._states.values()
                if state.debounce_task is not None and not state.debounce_task.done()
            ]
        for task in tasks:
            assert task is not None
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _schedule_debounce_locked(self, session_id: str, state: SessionState) -> None:
        if state.debounce_task is not None and not state.debounce_task.done():
            state.debounce_task.cancel()
        state.debounce_task = asyncio.create_task(
            self._debounce_then_run(session_id),
            name=f"hub-debounce-{session_id}",
        )

    async def _debounce_then_run(self, session_id: str) -> None:
        while not self._stopping:
            async with self._lock:
                state = self._states.get(session_id)
                if state is None:
                    return
                deadline = state.debounce_deadline
                if deadline is None:
                    return
                sleep_seconds = max(0.0, deadline - asyncio.get_running_loop().time())
            await asyncio.sleep(sleep_seconds)

            async with self._lock:
                state = self._states.get(session_id)
                if state is None:
                    return

                now = asyncio.get_running_loop().time()
                if state.debounce_deadline is not None and now < state.debounce_deadline:
                    # 防抖窗口内有新消息时会重置截止时间，这里继续等待直到窗口稳定。
                    continue
                if state.running:
                    return
                if not state.pending_messages:
                    state.debounce_task = None
                    self._cleanup_state_locked(session_id, state)
                    return

                merged_message = "\n".join(state.pending_messages)
                state.pending_messages.clear()
                state.running = True
                state.debounce_task = None
                state.debounce_deadline = None

            await self._run_once(session_id=session_id, user_message=merged_message)
            return

    async def _run_once(self, session_id: str, user_message: str) -> None:
        run_started_at = start_timer()
        log_info(
            self._logger,
            "hub.session_run_started",
            session_id=session_id,
            user_message_len=len(user_message),
        )
        try:
            reply = await self._outbound_client.call_agent(
                session_id=session_id,
                user_message=user_message,
            )
            await self._outbound_client.send_reply(session_id=session_id, content=reply)
            log_info(
                self._logger,
                "hub.session_run_completed",
                session_id=session_id,
                reply_len=len(reply),
                elapsed_ms=elapsed_ms(run_started_at),
            )
        except Exception:
            log_exception(
                self._logger,
                "hub.session_run_failed",
                session_id=session_id,
                elapsed_ms=elapsed_ms(run_started_at),
            )
        finally:
            async with self._lock:
                state = self._states.get(session_id)
                if state is None:
                    return

                state.running = False
                if state.pending_messages:
                    if state.debounce_deadline is None:
                        state.debounce_deadline = (
                            asyncio.get_running_loop().time() + self._debounce_seconds
                        )
                    self._schedule_debounce_locked(session_id, state)
                    return

                self._cleanup_state_locked(session_id, state)

    def _cleanup_state_locked(self, session_id: str, state: SessionState) -> None:
        if state.running:
            return
        if state.pending_messages:
            return
        if state.debounce_task is not None and not state.debounce_task.done():
            return
        self._states.pop(session_id, None)
