from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from xml.etree import ElementTree

from .adapter_registry import AdapterRegistry
from .internal_clients import AgentClient

IdleCallback = Callable[[str, "SessionRunner"], Awaitable[None]]
LOGGER = logging.getLogger(__name__)


class SessionRunner:
    """渠道无关的防抖与 agent 串行调度器。"""

    def __init__(
        self, session_id: str, adapter_key: tuple[str, str], agent: AgentClient,
        adapters: AdapterRegistry, debounce_seconds: float, on_idle: IdleCallback,
    ) -> None:
        self.session_id = session_id
        self._adapter_key = adapter_key
        self._agent = agent
        self._adapters = adapters
        self._debounce = debounce_seconds
        self._on_idle = on_idle
        self._pending: list[str] = []
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._lock = asyncio.Lock()

    async def submit(self, input_xml: str) -> None:
        async with self._lock:
            if self._running:
                queue = True
            else:
                queue = False
                self._pending.append(input_xml)
                if self._task is not None:
                    self._task.cancel()
                self._task = asyncio.create_task(self._debounce_then_run())
        if queue:
            await self._agent.queue(self.session_id, input_xml)

    async def _debounce_then_run(self) -> None:
        try:
            await asyncio.sleep(self._debounce)
        except asyncio.CancelledError:
            return
        async with self._lock:
            batch = list(self._pending)
            self._pending.clear()
            self._running = True
            self._task = None
        input_xml = _merge_messages(batch)
        try:
            output_xml = await self._agent.chat(self.session_id, input_xml)
            await self._adapters.deliver_reply(self._adapter_key, self.session_id, output_xml)
        except Exception:
            # asyncio task 是调度边界；在这里统一记录，避免无人 await 的任务只产生模糊警告。
            LOGGER.exception("session run failed", extra={"session_id": self.session_id})
        finally:
            async with self._lock:
                self._running = False
            await self._on_idle(self.session_id, self)

    async def is_idle(self) -> bool:
        async with self._lock:
            return not self._running and not self._pending and (self._task is None or self._task.done())

    async def shutdown(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


def _merge_messages(items: list[str]) -> str:
    root = ElementTree.Element("messages")
    for raw in items:
        source = ElementTree.fromstring(raw)
        if source.tag != "messages":
            raise ValueError("adapter input_xml root must be <messages>")
        root.extend(list(source))
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
