from __future__ import annotations

import json
from dataclasses import dataclass
from xml.etree import ElementTree

from ..logger import elapsed_ms, start_timer
from .llm_client import LlmClient
from .memory_compression_scheduler import MemoryCompressionScheduler, NoopMemoryCompressionScheduler
from .memory_client import MemoryClient
from .mcp_gateway import McpGateway
from .observability import Observability, RunTrace
from .session import Session
from .types.context import Context
from .types.llm import LlmResponse, Message, ToolCall

LLM_FALLBACK_REPLY = "笨蛋，刚才脑袋短路了一下，稍后再试试喵。"


@dataclass(frozen=True)
class AgentReply:
    output_xml: str


class Agent:
    """可复用的 Agent 单例，对 Session 执行推理。"""

    def __init__(
        self,
        llm_client: LlmClient,
        mcp_gateway: McpGateway,
        max_turns: int,
        max_retries: int,
        temperature: float,
        observability: Observability,
        memory_client: MemoryClient | None = None,
        memory_compression_scheduler: MemoryCompressionScheduler | None = None,
        memory_enabled: bool = False,
        memory_compress_every_n_records: int = 10,
    ) -> None:
        self._llm_client = llm_client
        self._mcp_gateway = mcp_gateway
        self._max_turns = max_turns
        self._max_retries = max_retries
        self._temperature = temperature
        self._observability = observability
        self._memory_client = memory_client
        self._memory_compression_scheduler = (
            memory_compression_scheduler or NoopMemoryCompressionScheduler()
        )
        self._memory_enabled = memory_enabled
        self._memory_compress_every_n_records = memory_compress_every_n_records

    def run(self, session: Session, user_message: str) -> AgentReply:
        """在指定 Session 上执行一轮推理循环，返回 AICHAN XML 回复。"""
        run_started_at = start_timer()

        staged_messages: list[Message] = []
        pending_user_messages = [user_message]

        self._refresh_memory(session)

        with session._lock:
            message_count = session.message_count_locked(len(pending_user_messages))

        run_trace = self._observability.start_run(
            session_id=session.session_id,
            message_count=message_count,
            max_turns=self._max_turns,
            agent_metadata=session.metadata,
        )

        try:
            for turn_idx in range(self._max_turns):
                turn = turn_idx + 1
                _stage_message(staged_messages, role="system", content=_turn_xml(index=turn))
                _stage_user_messages(staged_messages, pending_user_messages)
                pending_user_messages = []

                with session._lock:
                    input_messages = session.render_input_messages_locked(staged_messages)

                llm_response = self._generate_turn_response(
                    run_trace=run_trace,
                    turn=turn,
                    input_messages=input_messages,
                )

                if llm_response.finish_reason == "stop":
                    queued_messages = _drain_queued_user_messages(session)
                    if queued_messages:
                        # 最终回复只有在真正发给用户时才写入上下文。
                        # 这里若已收到新消息，就让这一轮结果失效，避免旧回复污染后续输入。
                        pending_user_messages = queued_messages
                        continue

                    _stage_message(
                        staged_messages,
                        role="assistant",
                        content=llm_response.content,
                    )
                    _commit_staged_messages(session, staged_messages)
                    self._compress_memory_if_due(session)
                    duration_ms = elapsed_ms(run_started_at)
                    self._observability.finish_run_success(
                        run=run_trace,
                        output={"output_xml": llm_response.content},
                        duration_ms=duration_ms,
                    )
                    return AgentReply(output_xml=llm_response.content)

                _stage_message(
                    staged_messages,
                    role="assistant",
                    content=llm_response.content,
                    tool_calls=llm_response.tool_calls,
                )

                for tool_call in llm_response.tool_calls:
                    tool_call_id = tool_call.id
                    tool_name = tool_call.function.name
                    tool_args_str = tool_call.function.arguments
                    tool_started_at = start_timer()

                    try:
                        tool_args = (
                            json.loads(tool_args_str)
                            if isinstance(tool_args_str, str)
                            else tool_args_str
                        )
                        tool_call_result = self._mcp_gateway.call_tool(
                            tool_name=tool_name,
                            tool_args=tool_args,
                        )
                        self._observability.tool_span(
                            run=run_trace,
                            turn=turn,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            status="ok",
                            error=None,
                            duration_ms=elapsed_ms(tool_started_at),
                            output=tool_call_result,
                        )
                    except Exception as exc:
                        tool_args_fallback = {"raw_arguments": str(tool_args_str)}
                        tool_call_result = json.dumps(
                            {"error": f"tool `{tool_name}` failed: {exc}"},
                            ensure_ascii=False,
                        )
                        self._observability.tool_span(
                            run=run_trace,
                            turn=turn,
                            tool_name=tool_name,
                            tool_args=tool_args_fallback,
                            status="failed",
                            error=str(exc),
                            duration_ms=elapsed_ms(tool_started_at),
                            output=tool_call_result,
                        )

                    _stage_message(
                        staged_messages,
                        role="tool",
                        content=tool_call_result,
                        tool_call_id=tool_call_id,
                    )

                queued_messages = _drain_queued_user_messages(session)
                # 工具结果必须紧跟对应 tool_calls；队列消息延后到下一轮 turn marker 后，
                # 既保留轮次边界，也避免破坏 OpenAI tool-call 消息顺序约束。
                pending_user_messages = queued_messages

            raise RuntimeError(
                "Agent failed to complete the task within "
                f"{self._max_turns} turns of interaction."
            )
        except Exception as exc:
            duration_ms = elapsed_ms(run_started_at)
            self._observability.finish_run_error(
                run=run_trace,
                error=str(exc),
                duration_ms=duration_ms,
            )
            # 生成异常和最终 XML 非法统一视为本轮失败，超过重试预算后收口为固定兜底回复，
            # 这样外层调用方不需要区分模型错误类型，也不会把半截 XML 泄漏给下游。
            output_xml = _text_reply_xml(LLM_FALLBACK_REPLY)
            _stage_message(staged_messages, role="assistant", content=output_xml)
            _commit_staged_messages(session, staged_messages)
            return AgentReply(output_xml=output_xml)

    def _refresh_memory(self, session: Session) -> None:
        if not self._memory_enabled or self._memory_client is None:
            return
        try:
            memory_markdown = self._memory_client.read(session.session_id)
        except Exception:
            with session._lock:
                session.clear_memory_locked()
            return
        with session._lock:
            session.set_memory_markdown_locked(memory_markdown)

    def _compress_memory_if_due(self, session: Session) -> None:
        if not self._memory_enabled or self._memory_client is None:
            return
        with session._lock:
            snapshot = session.prepare_memory_compression_locked(
                self._memory_compress_every_n_records
            )
            if snapshot is None:
                return
        self._memory_compression_scheduler.schedule(session, snapshot)

    def _generate_turn_response(
        self,
        *,
        run_trace: RunTrace,
        turn: int,
        input_messages: list[Message],
    ) -> LlmResponse:
        """统一处理单轮生成重试。

        这里把“LLM 调用异常”和“最终 stop 输出不是合法 XML”收敛成同一类失败。
        工具调用轮次不在这里重放，避免重复执行工具；只有本轮的生成步骤会按预算重试。
        """
        last_error: Exception | None = None
        tools_schema = self._mcp_gateway.get_tools_schema()

        for attempt in range(self._max_retries + 1):
            try:
                llm_started_at = start_timer()
                llm_response = self._llm_client.generate(
                    messages=input_messages,
                    tools_schema=tools_schema,
                    temperature=self._temperature,
                )
                llm_elapsed_ms = elapsed_ms(llm_started_at)

                self._observability.llm_generation(
                    run=run_trace,
                    turn=turn,
                    input_messages=input_messages,
                    output_content=llm_response.content,
                    output_tool_calls=llm_response.tool_calls,
                    finish_reason=llm_response.finish_reason,
                    model=self._llm_client.model_name,
                    duration_ms=llm_elapsed_ms,
                )

                if llm_response.finish_reason == "tool_calls":
                    return llm_response

                if llm_response.finish_reason != "stop":
                    raise RuntimeError(
                        "LLM response ended with unexpected reason: "
                        f"{llm_response.finish_reason}"
                    )

                if not _is_well_formed_xml(llm_response.content):
                    raise ValueError("LLM final reply is not valid XML")

                return llm_response
            except Exception as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    raise

        if last_error is not None:
            raise last_error
        raise RuntimeError("LLM turn retry loop exited unexpectedly")


def _is_well_formed_xml(raw: str) -> bool:
    try:
        ElementTree.fromstring(raw)
    except (ElementTree.ParseError, TypeError):
        return False
    return True


def _text_reply_xml(text: str) -> str:
    root = ElementTree.Element("reply")
    child = ElementTree.SubElement(root, "text")
    child.text = text
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def _stage_message(
    staged_messages: list[Message],
    *,
    role: str,
    content: str,
    tool_calls: list[ToolCall] | None = None,
    tool_call_id: str | None = None,
) -> None:
    staged = Context()
    staged.add_message(
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )
    staged_messages.extend(staged.messages)


def _turn_xml(index: int) -> str:
    root = ElementTree.Element("turn", {"index": str(index)})
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


def _commit_staged_messages(
    session: Session,
    staged_messages: list[Message],
) -> None:
    with session._lock:
        session.append_record_messages_locked(staged_messages)


def _drain_queued_user_messages(session: Session) -> list[str]:
    with session._lock:
        return session.drain_queued_user_messages_locked()


def _stage_user_messages(
    staged_messages: list[Message],
    user_messages: list[str],
) -> None:
    for user_message in user_messages:
        _stage_message(staged_messages, role="user", content=user_message)
