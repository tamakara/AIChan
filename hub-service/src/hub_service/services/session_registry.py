from __future__ import annotations

import asyncio
from typing import Any

from ..router.schemas import AgentInboundEvent
from .message_xml import FileUrlResolverProtocol, InputMediaStorageProtocol
from .napcat_ws import get_session_key
from .outbound_client import OutboundClient
from .session_runner import SessionRunner


class SessionRegistry:
    """会话注册中心 — 按 OneBot 原生 session key 管理 SessionRunner。"""

    def __init__(
        self,
        outbound_client: OutboundClient,
        media_storage: InputMediaStorageProtocol | None,
        debounce_seconds: float,
        file_resolver: FileUrlResolverProtocol | None = None,
    ) -> None:
        self._outbound_client = outbound_client
        self._media_storage = media_storage
        self._file_resolver = file_resolver
        self._debounce_seconds = debounce_seconds
        self._runners: dict[str, SessionRunner] = {}
        self._agent_session_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._stopping = False

    async def submit_event(self, raw_event: dict[str, Any]) -> None:
        """接收原始 OneBot v11 事件，路由到对应 SessionRunner。"""
        session_key = get_session_key(raw_event)

        async with self._lock:
            runner = self._runners.get(session_key)
            if runner is None:
                agent_session_id = self._agent_session_ids.get(session_key)
                if agent_session_id is None:
                    agent_session_id = await self._outbound_client.create_session(
                        hub_session_key=session_key,
                        metadata=_agent_metadata(raw_event),
                    )
                    self._agent_session_ids[session_key] = agent_session_id

                runner = SessionRunner(
                    session_key=session_key,
                    agent_session_id=agent_session_id,
                    outbound_client=self._outbound_client,
                    media_storage=self._media_storage,
                    file_resolver=self._file_resolver,
                    debounce_seconds=self._debounce_seconds,
                    on_idle=self._on_runner_idle,
                )
                self._runners[session_key] = runner

            await runner.submit_message(
                AgentInboundEvent(event=raw_event)
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

    async def _on_runner_idle(self, session_key: str, runner: SessionRunner) -> None:
        if self._stopping:
            return
        async with self._lock:
            if self._stopping:
                return
            if self._runners.get(session_key) is runner:
                if await runner.is_idle():
                    self._runners.pop(session_key, None)


def _agent_metadata(raw_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": "qq",
        "user_id": raw_event["user_id"],
        "self_id": raw_event["self_id"],
    }
