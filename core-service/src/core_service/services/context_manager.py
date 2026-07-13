from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

from ..adapters.protocol import SkillDocument
from .memory_client import MemoryClient
from .skills import LocalSkillRepository
from .types.llm import Message

MEMORY_SYSTEM_PREFIX = "以下是该会话的长期记忆；为空时表示暂无可用记忆："


@dataclass(frozen=True)
class RecordEntry:
    seq: int
    recorded_at: str
    message: Message


@dataclass
class ConversationContext:
    session_id: str
    metadata: dict[str, Any]
    history: list[Message] = field(default_factory=list)
    records: list[RecordEntry] = field(default_factory=list)
    queued_user_messages: list[str] = field(default_factory=list)
    memory_markdown: str = ""
    file_refs: set[str] = field(default_factory=set)
    revision: int = 0
    next_record_seq: int = 0
    compression_in_flight: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass(frozen=True)
class ContextSnapshot:
    session_id: str
    revision: int
    metadata: dict[str, Any]
    messages: list[Message]
    allowed_file_refs: frozenset[str]


class ContextManager:
    """会话状态唯一所有者；Agent 只读取快照并提交完整的成功轮次。"""

    def __init__(
        self,
        *,
        system_prompt_path: Path,
        skills: LocalSkillRepository,
        memory_client: MemoryClient | None,
        compress_every_n_records: int,
        max_turns: int,
    ) -> None:
        self._system_prompt = system_prompt_path.read_text(encoding="utf-8").strip()
        if not self._system_prompt:
            raise ValueError("system.md 不能为空")
        self._skills = skills
        self._skills.resolve()
        self._memory = memory_client
        self._compress_every = compress_every_n_records
        self._max_turns = max_turns
        self._contexts: dict[str, ConversationContext] = {}
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    async def create(self, session_id: str, metadata: dict[str, Any]) -> ConversationContext:
        async with self._lock:
            existing = self._contexts.get(session_id)
            if existing is not None:
                return existing
            context = ConversationContext(session_id=session_id, metadata={**metadata, "session_id": session_id})
            self._contexts[session_id] = context
            return context

    async def get(self, session_id: str) -> ConversationContext | None:
        async with self._lock:
            return self._contexts.get(session_id)

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            return self._contexts.pop(session_id, None) is not None

    async def queue(self, session_id: str, messages_xml: str, file_refs: set[str] | frozenset[str]) -> None:
        context = await self._require(session_id)
        async with context.lock:
            context.queued_user_messages.append(messages_xml)
            context.file_refs.update(file_refs)
            context.revision += 1

    async def drain_queued(self, session_id: str) -> list[str]:
        context = await self._require(session_id)
        async with context.lock:
            queued = list(context.queued_user_messages)
            context.queued_user_messages.clear()
            return queued

    async def has_queued(self, session_id: str) -> bool:
        context = await self._require(session_id)
        async with context.lock:
            return bool(context.queued_user_messages)

    async def snapshot(self, session_id: str, staged: list[Message], adapter_skills: list[SkillDocument]) -> ContextSnapshot:
        context = await self._require(session_id)
        await self._refresh_memory(context)
        local_skills = sorted(self._skills.resolve(), key=lambda item: item.id)
        current_adapter_skills = sorted((item for item in adapter_skills if item.enabled), key=lambda item: item.id)
        async with context.lock:
            messages: list[Message] = [{"role": "system", "content": self._system_prompt}]
            for skill in [*local_skills, *current_adapter_skills]:
                messages.append({"role": "system", "content": f'<skill id="{skill.id}" version="{skill.version}">\n{skill.content}\n</skill>'})
            messages.append({"role": "system", "content": _session_xml(context.session_id, context.metadata, self._max_turns)})
            if context.memory_markdown:
                messages.append({"role": "system", "content": f"{MEMORY_SYSTEM_PREFIX}\n{context.memory_markdown}"})
            messages.extend(dict(item) for item in context.history)
            messages.extend(dict(item) for item in staged)
            return ContextSnapshot(
                session_id=context.session_id,
                revision=context.revision,
                metadata=dict(context.metadata),
                messages=messages,
                allowed_file_refs=frozenset(context.file_refs),
            )

    async def add_file_refs(self, session_id: str, refs: set[str] | frozenset[str]) -> None:
        context = await self._require(session_id)
        async with context.lock:
            context.file_refs.update(refs)

    async def file_ref_allowed(self, session_id: str, file_ref: str) -> bool:
        context = await self._require(session_id)
        async with context.lock:
            return file_ref in context.file_refs

    async def commit(self, session_id: str, messages: list[Message]) -> None:
        context = await self._require(session_id)
        async with context.lock:
            self._commit_locked(context, messages)

    async def commit_if_no_queue(self, session_id: str, messages: list[Message]) -> list[str]:
        """在同一把会话锁内检查追入消息并提交，消除最终回复与新消息之间的竞态。"""
        context = await self._require(session_id)
        async with context.lock:
            if context.queued_user_messages:
                queued = list(context.queued_user_messages)
                context.queued_user_messages.clear()
                return queued
            self._commit_locked(context, messages)
            return []

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _refresh_memory(self, context: ConversationContext) -> None:
        if self._memory is None:
            return
        try:
            content = await self._memory.read(context.session_id)
        except Exception:
            return
        async with context.lock:
            context.memory_markdown = content.strip()

    def _commit_locked(self, context: ConversationContext, messages: list[Message]) -> None:
        for message in messages:
            frozen = dict(message)
            context.history.append(frozen)
            if _is_structural_turn(frozen):
                continue
            context.next_record_seq += 1
            context.records.append(RecordEntry(context.next_record_seq, datetime.now().astimezone().isoformat(timespec="seconds"), frozen))
        should_compress = self._memory is not None and not context.compression_in_flight and len(context.records) >= self._compress_every
        if should_compress:
            context.compression_in_flight = True
            target_seq = context.records[-1].seq
            text = _format_records(context.records)
            task = asyncio.create_task(self._compress(context, target_seq, text))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _compress(self, context: ConversationContext, target_seq: int, text: str) -> None:
        assert self._memory is not None
        try:
            result = await self._memory.compress(context.session_id, text)
        except Exception:
            async with context.lock:
                context.compression_in_flight = False
            return
        async with context.lock:
            context.memory_markdown = result.content_markdown.strip()
            context.records = [entry for entry in context.records if entry.seq > target_seq]
            context.history = [entry.message for entry in context.records]
            context.compression_in_flight = False

    async def _require(self, session_id: str) -> ConversationContext:
        context = await self.get(session_id)
        if context is None:
            raise KeyError("session not found")
        return context


def _session_xml(session_id: str, metadata: dict[str, Any], max_turns: int) -> str:
    attributes = {"session_id": session_id, "max_turn": str(max_turns)}
    for key in ("adapter_id", "instance_id", "conversation_type", "conversation_id", "bot_id"):
        if metadata.get(key) is not None:
            attributes[key] = str(metadata[key])
    rendered = " ".join(f"{key}={quoteattr(value)}" for key, value in attributes.items())
    return f"<session {rendered} />"


def _format_records(records: list[RecordEntry]) -> str:
    lines: list[str] = []
    for entry in records:
        role = str(entry.message.get("role", ""))
        content = str(entry.message.get("content", ""))
        for line in content.splitlines() or [""]:
            if line.strip():
                lines.append(f"[{entry.recorded_at}] {role}: {line}")
    return "\n".join(lines)


def _is_structural_turn(message: Message) -> bool:
    content = str(message.get("content", "")).strip()
    return message.get("role") == "system" and content.startswith("<turn ") and content.endswith("/>")
