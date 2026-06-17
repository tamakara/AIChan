from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any
from xml.etree import ElementTree

from .prompts import SYSTEM_PROMPT
from .types.context import Context
from .types.llm import Message

MEMORY_EMPTY_PLACEHOLDER = "暂无可用长期记忆。"
MEMORY_SYSTEM_PREFIX = "以下是该会话的长期记忆；为空时表示暂无可用记忆："


@dataclass(frozen=True)
class RecordEntry:
    recorded_at: str
    message: Message


class Session:
    """一次会话的上下文，独立于 Agent 进行管理。"""

    def __init__(self, session_id: str, metadata: dict[str, Any], max_turns: int) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._queued_user_messages: list[str] = []
        self._record_entries: list[RecordEntry] = []
        self._completed_chat_count = 0
        self._memory_enabled = False
        self._context = Context()
        # 系统提示词 + 会话标识
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=_session_xml(
                session_id=session_id,
                metadata=self._metadata,
                max_turns=max_turns,
            ),
        )

    @property
    def messages(self) -> list[Message]:
        return self._context.messages

    def render_input_messages_locked(self, staged_messages: list[Message]) -> list[Message]:
        return list(self._context.messages) + list(staged_messages)

    def message_count_locked(self, pending_user_message_count: int) -> int:
        return len(self._context.messages) + pending_user_message_count

    def set_memory_markdown_locked(self, memory_markdown: str) -> None:
        content = _memory_system_message(memory_markdown)
        if self._memory_enabled:
            self._context.messages[2] = {"role": "system", "content": content}
            return
        self._context.messages.insert(2, {"role": "system", "content": content})
        self._memory_enabled = True

    def clear_memory_locked(self) -> None:
        if not self._memory_enabled:
            return
        del self._context.messages[2]
        self._memory_enabled = False

    def append_record_messages_locked(self, messages: list[Message]) -> None:
        for message in messages:
            # 记忆压缩依赖的是“当时看见的记录”，所以这里先冻结一份消息快照并带上本地时间。
            # 这样后续即使会话上下文继续增长，已写入记忆日志的每行时间和内容都不会漂移。
            self._context.messages.append(message)
            self._record_entries.append(
                RecordEntry(recorded_at=_current_recorded_at(), message=dict(message))
            )

    def record_messages_locked(self) -> list[Message]:
        return [entry.message for entry in self._record_entries]

    def record_messages_text_locked(self) -> str:
        lines: list[str] = []
        for entry in self._record_entries:
            lines.extend(_format_record_entry_lines(entry))
        return "\n".join(lines)

    def mark_chat_completed_locked(self, compress_every_n_chats: int) -> bool:
        self._completed_chat_count += 1
        if compress_every_n_chats <= 0:
            return False
        if self._completed_chat_count < compress_every_n_chats:
            return False
        self._completed_chat_count = 0
        return True

    def replace_memory_and_clear_records_locked(self, memory_markdown: str) -> None:
        self.set_memory_markdown_locked(memory_markdown)
        del self._context.messages[self._record_start_index :]
        self._record_entries.clear()

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

    @property
    def _record_start_index(self) -> int:
        return 3 if self._memory_enabled else 2


class SessionRegistry:
    """会话注册中心，管理 Session 的创建/查找/删除。"""

    def __init__(self, max_turns: int) -> None:
        self._max_turns = max_turns
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(self, session_id: str, metadata: dict[str, Any]) -> Session:
        with self._lock:
            metadata_with_id = {**metadata, "session_id": session_id}
            session = Session(
                session_id=session_id,
                metadata=metadata_with_id,
                max_turns=self._max_turns,
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
    for key in ("platform", "session_type", "user_id", "group_id", "self_id"):
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
