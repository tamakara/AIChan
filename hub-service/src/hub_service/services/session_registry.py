from __future__ import annotations

import asyncio
from typing import Any

from .adapter_registry import AdapterRegistry
from .internal_clients import AgentClient
from .protocol import PublishedEvent, session_id_for
from .session_runner import SessionRunner


class SessionRegistry:
    def __init__(self, agent: AgentClient, adapters: AdapterRegistry, debounce_seconds: float) -> None:
        self._agent = agent
        self._adapters = adapters
        self._debounce = debounce_seconds
        self._runners: dict[str, SessionRunner] = {}
        self._routes: dict[str, tuple[str, str]] = {}
        self._created_sessions: set[str] = set()
        self._lock = asyncio.Lock()

    async def submit_event(self, adapter_key: tuple[str, str], event: PublishedEvent) -> None:
        session_id = session_id_for(*adapter_key, event.conversation_type, event.conversation_id)
        async with self._lock:
            runner = self._runners.get(session_id)
            if runner is None:
                metadata: dict[str, Any] = {
                    "adapter_id": adapter_key[0], "instance_id": adapter_key[1],
                    "conversation_type": event.conversation_type,
                    "conversation_id": event.conversation_id,
                }
                if event.bot_id is not None:
                    metadata["bot_id"] = event.bot_id
                if session_id not in self._created_sessions:
                    await self._agent.create_session(session_id, metadata)
                    self._created_sessions.add(session_id)
                runner = SessionRunner(
                    session_id, adapter_key, self._agent, self._adapters,
                    self._debounce, self._on_idle,
                )
                self._runners[session_id] = runner
                self._routes[session_id] = adapter_key
        await runner.submit(event.input_xml)

    async def invoke(self, session_id: str, capability: str, arguments: dict[str, Any]) -> Any:
        key = self._routes.get(session_id)
        if key is None:
            raise KeyError("session not found")
        return await self._adapters.invoke(key, session_id, capability, arguments)

    async def _on_idle(self, session_id: str, runner: SessionRunner) -> None:
        async with self._lock:
            if self._runners.get(session_id) is runner and await runner.is_idle():
                self._runners.pop(session_id, None)

    async def shutdown(self) -> None:
        async with self._lock:
            runners = list(self._runners.values())
            self._runners.clear()
        await asyncio.gather(*(runner.shutdown() for runner in runners), return_exceptions=True)
