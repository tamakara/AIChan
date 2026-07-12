from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from ..services.agent import Agent
from ..services.context_manager import ContextManager
from .protocol import PublishedEvent, session_id_for
from .registry import AdapterRegistry
from .xml_codec import XmlMessageCodec

LOGGER = logging.getLogger(__name__)


@dataclass
class SessionRunner:
    session_id: str
    adapter_key: tuple[str, str]
    agent: Agent
    adapters: AdapterRegistry
    contexts: ContextManager
    codec: XmlMessageCodec
    debounce_seconds: float
    pending: list[str] = field(default_factory=list)
    pending_keys: set[str] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    running: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def submit(self, messages_xml: str, object_keys: frozenset[str]) -> None:
        async with self.lock:
            if self.running:
                queue = True
            else:
                queue = False
                self.pending.append(messages_xml)
                self.pending_keys.update(object_keys)
                if self.task is not None:
                    self.task.cancel()
                self.task = asyncio.create_task(self._debounce_then_run())
        if queue:
            await self.contexts.queue(self.session_id, messages_xml, object_keys)

    async def _debounce_then_run(self) -> None:
        try:
            await asyncio.sleep(self.debounce_seconds)
        except asyncio.CancelledError:
            return
        async with self.lock:
            batch = list(self.pending)
            keys = frozenset(self.pending_keys)
            self.pending.clear()
            self.pending_keys.clear()
            self.running = True
            self.task = None
        registration = self.adapters.registration(self.adapter_key)
        try:
            merged = self.codec.merge_messages(batch, registration)
            reply = await self.agent.run(session_id=self.session_id, adapter_key=self.adapter_key, messages_xml=merged.xml, object_keys=keys | merged.object_keys)
            await self.adapters.deliver_reply(self.adapter_key, self.session_id, reply.reply_xml, reply.allowed_object_keys)
        except Exception:
            LOGGER.exception("session run failed", extra={"session_id": self.session_id})
        finally:
            async with self.lock:
                self.running = False
            # 最终提交后到投递完成之间仍可能到达消息；这里重新挂起一次运行，避免队列滞留。
            if await self.contexts.has_queued(self.session_id):
                queued = await self.contexts.drain_queued(self.session_id)
                for item in queued:
                    await self.submit(item, frozenset())

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class SessionManager:
    def __init__(self, *, agent: Agent, adapters: AdapterRegistry, contexts: ContextManager, codec: XmlMessageCodec, debounce_seconds: float) -> None:
        self._agent = agent
        self._adapters = adapters
        self._contexts = contexts
        self._codec = codec
        self._debounce = debounce_seconds
        self._runners: dict[str, SessionRunner] = {}
        self._lock = asyncio.Lock()

    async def submit_event(self, adapter_key: tuple[str, str], event: PublishedEvent, object_keys: frozenset[str]) -> None:
        session_id = session_id_for(*adapter_key, event.conversation_type, event.conversation_id)
        async with self._lock:
            runner = self._runners.get(session_id)
            if runner is None:
                metadata = {"adapter_id": adapter_key[0], "instance_id": adapter_key[1], "conversation_type": event.conversation_type, "conversation_id": event.conversation_id}
                if event.bot_id is not None:
                    metadata["bot_id"] = event.bot_id
                await self._contexts.create(session_id, metadata)
                runner = SessionRunner(session_id, adapter_key, self._agent, self._adapters, self._contexts, self._codec, self._debounce)
                self._runners[session_id] = runner
        await runner.submit(event.messages_xml, object_keys)

    async def close(self) -> None:
        async with self._lock:
            runners = list(self._runners.values())
            self._runners.clear()
        await asyncio.gather(*(runner.close() for runner in runners), return_exceptions=True)
