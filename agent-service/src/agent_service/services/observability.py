from __future__ import annotations

import sys
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any, Protocol
from uuid import uuid4

import httpx

from ..logger import get_logger, log_exception, log_warning
from ..config import LangfuseSettings
from .types.llm import Message, ToolCall


TRACE_NAME = "agent.chat.run"


@dataclass
class RunTrace:
    run_id: str
    trace_name: str


@dataclass
class LangfuseRunTrace(RunTrace):
    context_manager: Any
    root_observation: Any


class Observability(Protocol):
    def start_run(
        self,
        *,
        agent_id: str,
        message_count: int,
        max_turns: int,
        agent_metadata: dict[str, Any],
    ) -> RunTrace: ...

    def llm_generation(
        self,
        *,
        run: RunTrace,
        turn: int,
        input_messages: list[Message],
        output_content: str,
        output_tool_calls: list[ToolCall],
        finish_reason: str,
        model: str,
        duration_ms: int,
    ) -> None: ...

    def tool_span(
        self,
        *,
        run: RunTrace,
        turn: int,
        tool_name: str,
        tool_args: dict[str, Any],
        status: str,
        error: str | None,
        duration_ms: int,
        output: str | None,
    ) -> None: ...

    def finish_run_success(
        self,
        *,
        run: RunTrace,
        reply: str,
        duration_ms: int,
    ) -> None: ...

    def finish_run_error(
        self,
        *,
        run: RunTrace,
        error: str,
        duration_ms: int,
    ) -> None: ...

    def flush(self, timeout_seconds: float) -> None: ...


class NoopObservability:
    def start_run(
        self,
        *,
        agent_id: str,
        message_count: int,
        max_turns: int,
        agent_metadata: dict[str, Any],
    ) -> RunTrace:
        return RunTrace(run_id=str(uuid4()), trace_name=TRACE_NAME)

    def llm_generation(
        self,
        *,
        run: RunTrace,
        turn: int,
        input_messages: list[Message],
        output_content: str,
        output_tool_calls: list[ToolCall],
        finish_reason: str,
        model: str,
        duration_ms: int,
    ) -> None:
        return

    def tool_span(
        self,
        *,
        run: RunTrace,
        turn: int,
        tool_name: str,
        tool_args: dict[str, Any],
        status: str,
        error: str | None,
        duration_ms: int,
        output: str | None,
    ) -> None:
        return

    def finish_run_success(
        self,
        *,
        run: RunTrace,
        reply: str,
        duration_ms: int,
    ) -> None:
        return

    def finish_run_error(
        self,
        *,
        run: RunTrace,
        error: str,
        duration_ms: int,
    ) -> None:
        return

    def flush(self, timeout_seconds: float) -> None:
        return


class LangfuseObservability:
    def __init__(self, settings: LangfuseSettings, client: Any | None = None) -> None:
        self._logger = get_logger("observability")
        if client is not None:
            self._client = client
            return

        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
            flush_at=settings.flush_at,
            flush_interval=settings.flush_interval,
            httpx_client=httpx.Client(timeout=settings.request_timeout),
        )

    def start_run(
        self,
        *,
        agent_id: str,
        message_count: int,
        max_turns: int,
        agent_metadata: dict[str, Any],
    ) -> RunTrace:
        run_id = str(uuid4())
        context_manager: Any | None = None
        try:
            run_metadata = {
                "agent_id": agent_id,
                "message_count": message_count,
                "max_turns": max_turns,
                "run_id": run_id,
                "agent_metadata": _to_jsonable(agent_metadata),
            }
            context_manager = self._client.start_as_current_observation(
                name=TRACE_NAME,
                as_type="chain",
                metadata=run_metadata,
            )
            root_observation = context_manager.__enter__()
            return LangfuseRunTrace(
                run_id=run_id,
                trace_name=TRACE_NAME,
                context_manager=context_manager,
                root_observation=root_observation,
            )
        except Exception:
            # 观测启动失败时降级为普通 RunTrace，确保主链路不受观测组件可用性影响。
            log_exception(
                self._logger,
                "agent.observability_start_failed",
                agent_id=agent_id,
            )
            if context_manager is not None:
                try:
                    context_manager.__exit__(*sys.exc_info())
                except Exception:
                    pass
            return RunTrace(run_id=run_id, trace_name=TRACE_NAME)

    def llm_generation(
        self,
        *,
        run: RunTrace,
        turn: int,
        input_messages: list[Message],
        output_content: str,
        output_tool_calls: list[ToolCall],
        finish_reason: str,
        model: str,
        duration_ms: int,
    ) -> None:
        if not isinstance(run, LangfuseRunTrace):
            return
        try:
            with run.root_observation.start_as_current_observation(
                name="agent.llm.generation",
                as_type="generation",
                model=model,
                input=_to_jsonable(input_messages),
                output=_to_jsonable(
                    {
                        "content": output_content,
                        "tool_calls": output_tool_calls,
                        "finish_reason": finish_reason,
                    }
                ),
                metadata={"turn": turn, "duration_ms": duration_ms},
            ):
                pass
        except Exception:
            log_exception(
                self._logger,
                "agent.observability_generation_failed",
                run_id=run.run_id,
                turn=turn,
            )

    def tool_span(
        self,
        *,
        run: RunTrace,
        turn: int,
        tool_name: str,
        tool_args: dict[str, Any],
        status: str,
        error: str | None,
        duration_ms: int,
        output: str | None,
    ) -> None:
        if not isinstance(run, LangfuseRunTrace):
            return
        try:
            with run.root_observation.start_as_current_observation(
                name="agent.tool.span",
                as_type="tool",
                input=_to_jsonable(tool_args),
                output=_to_jsonable(output),
                metadata={
                    "turn": turn,
                    "tool_name": tool_name,
                    "tool_args": _to_jsonable(tool_args),
                    "status": status,
                    "error": error,
                    "duration_ms": duration_ms,
                },
            ):
                pass
        except Exception:
            log_exception(
                self._logger,
                "agent.observability_tool_failed",
                run_id=run.run_id,
                tool_name=tool_name,
            )

    def finish_run_success(
        self,
        *,
        run: RunTrace,
        reply: str,
        duration_ms: int,
    ) -> None:
        if not isinstance(run, LangfuseRunTrace):
            return
        try:
            run.root_observation.update(
                output=reply,
                metadata={"status": "ok", "duration_ms": duration_ms},
            )
        except Exception:
            log_exception(
                self._logger,
                "agent.observability_finish_failed",
                run_id=run.run_id,
                status="ok",
            )
        finally:
            try:
                run.context_manager.__exit__(None, None, None)
            except Exception:
                log_exception(
                    self._logger,
                    "agent.observability_finish_failed",
                    run_id=run.run_id,
                    status="ok",
                )

    def finish_run_error(
        self,
        *,
        run: RunTrace,
        error: str,
        duration_ms: int,
    ) -> None:
        if not isinstance(run, LangfuseRunTrace):
            return
        try:
            run.root_observation.update(
                level="ERROR",
                status_message=error,
                metadata={"status": "failed", "duration_ms": duration_ms},
            )
        except Exception:
            log_exception(
                self._logger,
                "agent.observability_finish_failed",
                run_id=run.run_id,
                status="failed",
            )
        finally:
            try:
                run.context_manager.__exit__(None, None, None)
            except Exception:
                log_exception(
                    self._logger,
                    "agent.observability_finish_failed",
                    run_id=run.run_id,
                    status="failed",
                )

    def flush(self, timeout_seconds: float) -> None:
        done = Event()
        errors: list[Exception] = []

        def _flush() -> None:
            try:
                self._client.flush()
            except Exception as exc:
                errors.append(exc)
            finally:
                done.set()

        thread = Thread(target=_flush, daemon=True)
        thread.start()
        if not done.wait(timeout_seconds):
            # flush 使用超时保护，避免关停阶段被外部观测网络阻塞。
            log_warning(
                self._logger,
                "agent.observability_flush_timeout",
                timeout_seconds=timeout_seconds,
            )
            return
        if errors:
            log_warning(
                self._logger,
                "agent.observability_flush_failed",
                detail=str(errors[0]),
            )


def create_observability(settings: LangfuseSettings) -> Observability:
    if not settings.enabled:
        return NoopObservability()
    return LangfuseObservability(settings=settings)


def _to_jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_jsonable(model_dump(mode="json", exclude_none=True))
    return str(value)

