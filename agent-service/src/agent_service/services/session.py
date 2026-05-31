from __future__ import annotations

from threading import Lock
from typing import Any
from uuid import uuid4

from .prompts import SYSTEM_PROMPT
from .types.context import Context
from .types.llm import Message


class SessionPreempted(Exception):
    """当前生成已被同一会话的新请求抢占，应中止并返回 409。"""

    def __init__(self, session_id: str, my_gen: int, current_gen: int) -> None:
        super().__init__(
            f"session {session_id} preempted: generation {my_gen} -> {current_gen}"
        )
        self.session_id = session_id
        self.my_generation = my_gen
        self.current_generation = current_gen


class Session:
    """一次会话的上下文与状态，独立于 Agent 进行管理。

    Session 拥有独立的 Context（消息历史）、线程锁与 generation 计数器，
    是 Agent.run() 的执行对象。
    """

    def __init__(self, session_id: str, metadata: dict[str, Any]) -> None:
        self._session_id = session_id
        self._metadata = dict(metadata)
        self._lock = Lock()
        self._context = Context()
        self._generation = 0
        self._context.add_message(role="system", content=SYSTEM_PROMPT)

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def get_messages(self) -> list[Message]:
        return self._context.messages


class SessionRegistry:
    """会话注册中心，管理 Session 的生命周期（创建/查找/删除）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create(self, metadata: dict[str, Any]) -> Session:
        with self._lock:
            session_id = str(uuid4())
            session = Session(session_id=session_id, metadata=metadata)
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
