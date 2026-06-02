from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4

from .prompts import SYSTEM_PROMPT
from .types.context import Context


class Session:
    """一次会话的上下文，独立于 Agent 进行管理。"""

    def __init__(self, session_id: str, metadata: dict[str, Any]) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._context = Context()
        # 系统提示词 + 会话标识信息
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=f"<session_info>当前会话 ID: {session_id}</session_info>",
        )

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
            # 将 session_id 注入 metadata，确保调用方能在返回的 metadata 中获取
            metadata_with_id = {"session_id": session_id, **metadata}
            session = Session(session_id=session_id, metadata=metadata_with_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False
