from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from ..logger import elapsed_ms, start_timer
from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .observability import Observability
from .session import Session
from .types.context import Context
from .types.llm import Message, ToolCall

LLM_FALLBACK_REPLY = "笨蛋，刚才脑袋短路了一下，稍后再试试喵。"


@dataclass(frozen=True)
class AgentReply:
    output_xml: str


class Agent:
    """可复用的 Agent 单例，对 Session 执行推理。

    Agent 持有共享的 LLM 客户端、MCP 网关与可观测性实例，
    通过 run(session, ...) 在指定会话上执行 turn-loop，返回结构化回复。
    """

    def __init__(
        self,
        llm_client: LlmClient,
        mcp_gateway: McpGateway,
        max_turns: int,
        temperature: float,
        observability: Observability,
    ) -> None:
        self._llm_client = llm_client
        self._mcp_gateway = mcp_gateway
        self._max_turns = max_turns
        self._temperature = temperature
        self._observability = observability

    # ------------------------------------------------------------------
    # 会话执行
    # ------------------------------------------------------------------

    def run(self, session: Session, user_message: str) -> AgentReply:
        """在指定 Session 上执行一轮推理循环，返回 AICHAN XML 回复。"""
        run_started_at = start_timer()

        # ── 1. 暂存用户消息、启动观测 trace ──
        staged_messages: list[Message] = []
        pending_user_messages = [user_message]

        with session._lock:
            message_count = len(session._context.messages) + len(pending_user_messages)

        run_trace = self._observability.start_run(
            session_id=session.session_id,
            message_count=message_count,
            max_turns=self._max_turns,
            agent_metadata=session.metadata,
        )

        try:
            # ── 2. turn-loop：LLM 推理 + 工具调用 ──
            for turn_idx in range(self._max_turns):
                turn = turn_idx + 1
                _stage_message(staged_messages, role="system", content=_turn_xml(index=turn))
                _stage_user_messages(staged_messages, pending_user_messages)
                pending_user_messages = []

                with session._lock:
                    input_messages = list(session._context.messages) + list(staged_messages)

                llm_started_at = start_timer()
                llm_response = self._llm_client.generate(
                    messages=input_messages,
                    tools_schema=self._mcp_gateway.get_tools_schema(),
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

                _stage_message(
                    staged_messages,
                    role="assistant",
                    content=llm_response.content,
                    tool_calls=llm_response.tool_calls,
                )

                if llm_response.finish_reason != "tool_calls":
                    if llm_response.finish_reason == "stop":
                        queued_messages = _drain_queued_user_messages(session)
                        if queued_messages:
                            # 模型刚准备结束时若用户又发了消息，旧 final reply 已不再覆盖最新输入。
                            # 丢弃这条 assistant，插入新 user 后继续推理，避免未发送回复污染上下文。
                            staged_messages.pop()
                            pending_user_messages = queued_messages
                            continue

                        reply = _parse_agent_reply(llm_response.content)
                        _commit_staged_messages(session, staged_messages)
                        duration_ms = elapsed_ms(run_started_at)
                        self._observability.finish_run_success(
                            run=run_trace,
                            output={"output_xml": reply.output_xml},
                            duration_ms=duration_ms,
                        )
                        return reply
                    raise RuntimeError(
                        "LLM response ended with unexpected reason: "
                        f"{llm_response.finish_reason}"
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
                            tool_name=tool_name, tool_args=tool_args
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
            # LLM/API/MCP 边界的瞬时失败不再向 QQ 用户暴露 500。
            # 这里统一返回固定文案，避免按网络错误类型扩散细粒度异常分支。
            output_xml = _text_reply_xml(LLM_FALLBACK_REPLY)
            _stage_message(
                staged_messages,
                role="assistant",
                content=output_xml,
            )
            _commit_staged_messages(session, staged_messages)
            return AgentReply(output_xml=output_xml)


def _parse_agent_reply(raw: str) -> AgentReply:
    """把 LLM 最终输出收敛为 AICHAN XML 回复契约。

    hub-service 只消费 `<reply>`，因此非法 XML 不继续向下游扩散，而是包装为文本。
    这样模型偶发格式偏离时仍可回复用户，且不把容错逻辑分散到消息投递层。
    """
    try:
        root = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, TypeError):
        return AgentReply(output_xml=_text_reply_xml(raw))

    if root.tag != "reply":
        return AgentReply(output_xml=_text_reply_xml(raw))

    return AgentReply(
        output_xml=ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
    )


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
        session._context.messages.extend(staged_messages)


def _drain_queued_user_messages(session: Session) -> list[str]:
    with session._lock:
        return session.drain_queued_user_messages_locked()


def _stage_user_messages(
    staged_messages: list[Message],
    user_messages: list[str],
) -> None:
    for user_message in user_messages:
        _stage_message(staged_messages, role="user", content=user_message)
