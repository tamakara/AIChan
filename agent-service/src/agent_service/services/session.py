from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any
from xml.etree import ElementTree

from .prompts import BASE_SYSTEM_PROMPT
from .skill_client import RuntimeSkill
from .types.context import Context
from .types.llm import Message

MEMORY_EMPTY_PLACEHOLDER = "暂无可用长期记忆。"
MEMORY_SYSTEM_PREFIX = "以下是该会话的长期记忆；为空时表示暂无可用记忆："


@dataclass(frozen=True)
class RecordEntry:
    seq: int
    recorded_at: str
    message: Message


@dataclass(frozen=True)
class MemoryCompressionSnapshot:
    target_max_seq: int
    messages_text: str


class Session:
    """一次会话的上下文，独立于 Agent 进行管理。"""

    def __init__(
        self,
        session_id: str,
        metadata: dict[str, Any],
        max_turns: int,
        skills: list[RuntimeSkill] | None = None,
    ) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._queued_user_messages: list[str] = []
        self._record_entries: list[RecordEntry] = []
        self._next_record_seq = 0
        self._compression_snapshot: MemoryCompressionSnapshot | None = None
        self._memory_message: Message | None = None
        # 上下文拆成系统层、记忆层、记录层三部分管理，避免压缩阈值和清理逻辑依赖魔法切片。
        self._record_context = Context()
        self._max_turns = max_turns
        self._skills = list(skills or [])

    @property
    def messages(self) -> list[Message]:
        with self._lock:
            return self._all_messages_locked()

    def render_input_messages_locked(self, staged_messages: list[Message]) -> list[Message]:
        return self._all_messages_locked() + list(staged_messages)

    def message_count_locked(self, pending_user_message_count: int) -> int:
        return len(self._all_messages_locked()) + pending_user_message_count

    def set_memory_markdown_locked(self, memory_markdown: str) -> None:
        content = _memory_system_message(memory_markdown)
        self._memory_message = {"role": "system", "content": content}

    def clear_memory_locked(self) -> None:
        self._memory_message = None

    def set_skills_locked(self, skills: list[RuntimeSkill]) -> None:
        self._skills = list(skills)

    def append_record_messages_locked(self, messages: list[Message]) -> None:
        for message in messages:
            # 记忆压缩依赖的是“当时看见的记录”，所以这里先冻结一份消息快照并带上本地时间。
            # 这样后续即使会话上下文继续增长，已写入记忆日志的每行时间和内容都不会漂移。
            self._next_record_seq += 1
            self._record_context.messages.append(message)
            self._record_entries.append(
                RecordEntry(
                    seq=self._next_record_seq,
                    recorded_at=_current_recorded_at(),
                    message=dict(message),
                )
            )

    def record_messages_locked(self) -> list[Message]:
        return [entry.message for entry in self._record_entries]

    def record_messages_text_locked(self) -> str:
        return _format_record_entries_text(self._record_entries)

    def should_compress_records_locked(self, compress_every_n_records: int) -> bool:
        if compress_every_n_records <= 0:
            return False
        return len(self._record_context.messages) >= compress_every_n_records

    def prepare_memory_compression_locked(
        self,
        compress_every_n_records: int,
    ) -> MemoryCompressionSnapshot | None:
        if self._compression_snapshot is not None:
            return None
        if not self.should_compress_records_locked(compress_every_n_records):
            return None
        snapshot = MemoryCompressionSnapshot(
            target_max_seq=self._record_entries[-1].seq,
            messages_text=_format_record_entries_text(self._record_entries),
        )
        self._compression_snapshot = snapshot
        return snapshot

    def complete_memory_compression_locked(
        self,
        *,
        target_max_seq: int,
        memory_markdown: str,
    ) -> None:
        snapshot = self._compression_snapshot
        if snapshot is None or snapshot.target_max_seq != target_max_seq:
            return
        self.set_memory_markdown_locked(memory_markdown)
        self._record_entries = [
            entry for entry in self._record_entries if entry.seq > target_max_seq
        ]
        self._record_context.messages = [entry.message for entry in self._record_entries]
        self._compression_snapshot = None

    def fail_memory_compression_locked(self, *, target_max_seq: int) -> None:
        snapshot = self._compression_snapshot
        if snapshot is None or snapshot.target_max_seq != target_max_seq:
            return
        self._compression_snapshot = None

    def queue_user_message(self, user_message: str) -> None:
        with self._lock:
            self._queued_user_messages.append(user_message)

    def drain_queued_user_messages_locked(self) -> list[str]:
        queued = self._queued_user_messages.copy()
        self._queued_user_messages.clear()
        return queued

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def record_message_count_locked(self) -> int:
        return len(self._record_context.messages)

    def memory_message_locked(self) -> Message | None:
        return self._memory_message

    def compression_in_flight_locked(self) -> bool:
        return self._compression_snapshot is not None

    def _all_messages_locked(self) -> list[Message]:
        messages: list[Message] = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]
        for skill in self._skills:
            messages.append({
                "role": "system",
                "content": f'<skill id="{skill.id}" version="{skill.version}">\n{skill.content}\n</skill>',
            })
        messages.append({
            "role": "system",
            "content": _session_xml(self._session_id, self._metadata, self._max_turns),
        })
        if self._memory_message is not None:
            messages.append(self._memory_message)
        messages.extend(self._record_context.messages)
        return messages


class SessionRegistry:
    """会话注册中心，管理 Session 的创建/查找/删除。"""

    def __init__(self, max_turns: int) -> None:
        self._max_turns = max_turns
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(
        self,
        session_id: str,
        metadata: dict[str, Any],
        skills: list[RuntimeSkill] | None = None,
    ) -> Session:
        with self._lock:
            metadata_with_id = {**metadata, "session_id": session_id}
            session = Session(
                session_id=session_id,
                metadata=metadata_with_id,
                max_turns=self._max_turns,
                skills=skills,
            )
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def queue_message(self, session_id: str, user_message: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.queue_user_message(user_message)
            return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False


def _session_xml(session_id: str, metadata: dict[str, Any], max_turns: int) -> str:
    attributes = {
        "session_id": session_id,
        "max_turn": str(max_turns),
    }
    for key in ("adapter_id", "instance_id", "conversation_type", "conversation_id", "bot_id"):
        value = metadata.get(key)
        if value is not None:
            attributes[key] = str(value)
    root = ElementTree.Element("session", attributes)
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def _memory_system_message(memory_markdown: str) -> str:
    content = memory_markdown.strip() or MEMORY_EMPTY_PLACEHOLDER
    return f"{MEMORY_SYSTEM_PREFIX}\n{content}"


def _current_recorded_at() -> str:
    # 这里记录的是服务端实际写入记忆的本地时间，不追求“事件发生秒级真相”，
    # 但必须稳定、可读，方便后续把聊天轨迹当日志逐行压缩。
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _format_record_entries_text(entries: list[RecordEntry]) -> str:
    lines: list[str] = []
    for entry in entries:
        lines.extend(_format_record_entry_lines(entry))
    return "\n".join(lines)


def _format_record_entry_lines(entry: RecordEntry) -> list[str]:
    message = entry.message
    role = str(message.get("role", ""))
    content = str(message.get("content", ""))
    if _is_structural_turn_message(role=role, content=content):
        return []

    role_label = role
    tool_call_id = message.get("tool_call_id")
    if role == "tool" and tool_call_id is not None:
        role_label = f"tool[{tool_call_id}]"

    prefix = f"[{entry.recorded_at}] {role_label}"
    content_lines = _split_content_lines(content)

    lines = [f"{prefix}: {line}" for line in content_lines]
    if not lines:
        lines = [f"{prefix}:"]

    tool_calls = message.get("tool_calls")
    if tool_calls is not None:
        lines.append(f"{prefix}.tool_calls: {tool_calls}")
    return lines


def _split_content_lines(content: str) -> list[str]:
    return [line for line in content.splitlines() if line.strip()]


def _is_structural_turn_message(*, role: str, content: str) -> bool:
    # `<turn ... />` 只是 agent 内部的轮次分隔符，不是用户说过的话，也不是可复用事实。
    # 压缩时把它丢掉，能减少模型把结构当内容的机会。
    normalized = content.strip()
    return role == "system" and normalized.startswith("<turn ") and normalized.endswith("/>")
