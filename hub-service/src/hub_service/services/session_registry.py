from __future__ import annotations

import asyncio

from ..router.schemas import AgentInboundMessage
from .outbound_client import OutboundClient
from .session_runner import SessionRunner
from .stream_models import EventStreamMessage


class SessionRegistry:
    def __init__(
        self,
        outbound_client: OutboundClient,
        debounce_seconds: float,
        post_run_grace_seconds: float,
        max_wait_seconds: float,
    ) -> None:
        self._outbound_client = outbound_client
        self._debounce_seconds = debounce_seconds
        self._post_run_grace_seconds = post_run_grace_seconds
        self._max_wait_seconds = max_wait_seconds
        self._runners: dict[str, SessionRunner] = {}
        self._session_agent_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._stopping = False

    async def submit_event(self, event: EventStreamMessage) -> None:
        async with self._lock:
            runner = self._runners.get(event.session_id)
            if runner is None:
                agent_id = self._session_agent_ids.get(event.session_id)
                if agent_id is None:
                    agent_id = await self._outbound_client.create_agent(
                        session_id=event.session_id,
                        metadata={"session_id": event.session_id},
                    )
                    self._session_agent_ids[event.session_id] = agent_id
                # 注册中心统一创建 runner，确保同一 session 永远只会被单个对象串行处理。
                runner = SessionRunner(
                    session_id=event.session_id,
                    agent_id=agent_id,
                    outbound_client=self._outbound_client,
                    debounce_seconds=self._debounce_seconds,
                    post_run_grace_seconds=self._post_run_grace_seconds,
                    max_wait_seconds=self._max_wait_seconds,
                    on_idle=self._on_runner_idle,
                )
                self._runners[event.session_id] = runner
            await runner.submit_message(
                AgentInboundMessage(
                    user_id=event.user_id,
                    content=event.content,
                    event_time=extract_event_time(event),
                )
            )

    async def shutdown(self) -> None:
        self._stopping = True
        async with self._lock:
            runners = list(self._runners.values())
            self._runners.clear()
        await asyncio.gather(*(runner.shutdown() for runner in runners), return_exceptions=True)

    async def active_runner_count(self) -> int:
        async with self._lock:
            return len(self._runners)

    async def _on_runner_idle(self, session_id: str, runner: SessionRunner) -> None:
        if self._stopping:
            return
        async with self._lock:
            if self._stopping:
                return
            if self._runners.get(session_id) is runner:
                if await runner.is_idle():
                    self._runners.pop(session_id, None)


def extract_event_time(event: EventStreamMessage) -> str:
    # 只接受 OneBot 原始事件时间，避免把接入层入流时间误判为用户发言时间。
    time_value = event.raw_event.get("time")
    if isinstance(time_value, bool):
        raise ValueError("raw_event.time is required and must be an integer-like timestamp")
    if isinstance(time_value, int):
        return str(time_value)
    if isinstance(time_value, float) and time_value.is_integer():
        return str(int(time_value))
    if isinstance(time_value, str) and time_value.strip().isdigit():
        return str(int(time_value.strip()))
    raise ValueError("raw_event.time is required and must be an integer-like timestamp")
