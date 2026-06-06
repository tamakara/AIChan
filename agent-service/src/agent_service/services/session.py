from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from .prompts import SYSTEM_PROMPT
from .types.context import Context


class Session:
    """一次会话的上下文，独立于 Agent 进行管理。"""

    def __init__(self, session_id: str, metadata: dict[str, Any]) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._queued_user_messages: list[str] = []
        self._context = Context()
        # 系统提示词 + 会话标识
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=_session_info_xml(session_id=session_id, metadata=self._metadata),
        )

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


class SessionRegistry:
    """会话注册中心，管理 Session 的创建/查找/删除。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(self, metadata: dict[str, Any]) -> Session:
        with self._lock:
            session_id = str(uuid4())
            metadata_with_id = {"session_id": session_id, **metadata}
            session = Session(session_id=session_id, metadata=metadata_with_id)
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


def _session_info_xml(session_id: str, metadata: dict[str, Any]) -> str:
    root = ElementTree.Element("session_info")
    ElementTree.SubElement(root, "session_id").text = session_id
    for key in ("platform", "user_id", "self_id"):
        value = metadata.get(key)
        if value is not None:
            ElementTree.SubElement(root, key).text = str(value)
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
