from __future__ import annotations

from html import escape
from threading import Lock
from typing import Any
from uuid import uuid4

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .agent_core import AgentCore
from .prompts import SYSTEM_PROMPT
from .types.context import Context
from .types.llm import Message


class AgentRun:
    def __init__(self, agent_id: str, agent_core: AgentCore, metadata: dict[str, Any]) -> None:
        self._logger = get_logger("agent_run")
        self._agent_id = agent_id
        self._metadata = dict(metadata)
        self._agent_core = agent_core
        self._lock = Lock()
        self._context = Context()
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=_build_session_start_tag(
                agent_id=agent_id,
                metadata=self._metadata,
            ),
        )

    def run(self, user_message: str) -> str:
        run_started_at = start_timer()
        with self._lock:
            # 把日志与消息写入放在同一把会话锁内，确保日志时间线与上下文状态严格一致。
            log_info(
                self._logger,
                "agent_run.run_started",
                agent_id=self._agent_id,
                max_turns=self._agent_core.max_turns,
                message_len=len(user_message),
            )
            self._context.add_message(role="user", content=user_message)
            try:
                reply = self._agent_core.run(context=self._context)
                self._context.add_message(role="assistant", content=reply)
                log_info(
                    self._logger,
                    "agent_run.run_completed",
                    agent_id=self._agent_id,
                    reply_len=len(reply),
                    elapsed_ms=elapsed_ms(run_started_at),
                )
                return reply
            except Exception:
                log_exception(
                    self._logger,
                    "agent_run.run_failed",
                    agent_id=self._agent_id,
                    elapsed_ms=elapsed_ms(run_started_at),
                )
                raise

    def get_agent_id(self) -> str:
        return self._agent_id

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def get_messages(self) -> list[Message]:
        return self._context.messages


class AgentRunRegistry:
    def __init__(self, agent_core: AgentCore) -> None:
        self._agent_core = agent_core
        self._agent_runs: dict[str, AgentRun] = {}
        self._lock = Lock()

    def create(self, metadata: dict[str, Any]) -> AgentRun:
        with self._lock:
            agent_id = str(uuid4())
            agent_run = AgentRun(
                agent_id=agent_id,
                agent_core=self._agent_core,
                metadata=metadata,
            )
            self._agent_runs[agent_id] = agent_run
            return agent_run

    def get(self, agent_id: str) -> AgentRun | None:
        with self._lock:
            return self._agent_runs.get(agent_id)


def _build_session_start_tag(agent_id: str, metadata: dict[str, Any]) -> str:
    session_id = metadata.get("session_id")
    if isinstance(session_id, str) and session_id:
        return (
            '<session_start '
            f'agent_id="{escape(agent_id, quote=True)}" '
            f'session_id="{escape(session_id, quote=True)}"'
            ">"
        )
    return f'<session_start agent_id="{escape(agent_id, quote=True)}">'
