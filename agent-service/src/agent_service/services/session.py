from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4

from .prompts import SYSTEM_PROMPT
from .types.context import Context


class SessionInterrupted(Exception):
    """外部中断请求导致 run 被中止。"""


class Session:
    """一次会话的上下文，独立于 Agent 进行管理。"""

    def __init__(self, session_id: str, metadata: dict[str, Any]) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._generation = 0
        self._interrupt_target = -1
        self._context = Context()
        # 系统提示词 + 会话标识
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=f"<session_info>当前会话 ID: {session_id}</session_info>",
        )

    def begin_run(self) -> int:
        """开始新 run，返回递增后的 generation 用于中断检测。"""
        self._generation += 1
        return self._generation

    def interrupt(self) -> None:
        """标记当前 generation 为已中断。不影响后续的新 run。"""
        self._interrupt_target = self._generation

    def check_interrupt(self, my_gen: int) -> None:
        """仅当本 run 是中断目标时才抛出。"""
        if my_gen == self._interrupt_target:
            raise SessionInterrupted

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

    def interrupt(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            session.interrupt()
            return True

    def delete(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False
