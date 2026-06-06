from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from ..logger import elapsed_ms, start_timer
from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .observability import Observability
from .session import Session, SessionInterrupted

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
        """在指定 Session 上执行一轮推理循环，返回 AICHAN XML 回复。

        每次 run 开始时清除 interrupt 标记。
        LLM 返回后若检测到中断标记，抛 SessionInterrupted 且不写入上下文。
        """
        my_gen = session.begin_run()
        run_started_at = start_timer()

        # ── 1. 写入用户消息、启动观测 trace ──
        with session._lock:
            session._context.add_message(role="user", content=user_message)
            message_count = len(session._context.messages)

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

                with session._lock:
                    input_messages = list(session._context.messages)

                llm_started_at = start_timer()
                llm_response = self._llm_client.generate(
                    messages=input_messages,
                    tools_schema=self._mcp_gateway.get_tools_schema(),
                    temperature=self._temperature,
                )
                llm_elapsed_ms = elapsed_ms(llm_started_at)

                # LLM 返回后检测中断——仅针对本 run 的 generation，新 run 不受影响
                session.check_interrupt(my_gen)

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

                with session._lock:
                    session._context.add_message(
                        role="assistant",
                        content=llm_response.content,
                        tool_calls=llm_response.tool_calls,
                    )

                if llm_response.finish_reason != "tool_calls":
                    if llm_response.finish_reason == "stop":
                        reply = _parse_agent_reply(llm_response.content)
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

                    with session._lock:
                        session._context.add_message(
                            role="tool",
                            content=tool_call_result,
                            tool_call_id=tool_call_id,
                        )

            raise RuntimeError(
                "Agent failed to complete the task within "
                f"{self._max_turns} turns of interaction."
            )
        except SessionInterrupted:
            raise
        except Exception as exc:
            duration_ms = elapsed_ms(run_started_at)
            self._observability.finish_run_error(
                run=run_trace,
                error=str(exc),
                duration_ms=duration_ms,
            )
            # LLM/API/MCP 边界的瞬时失败不再向 QQ 用户暴露 500。
            # 这里统一返回固定文案，避免按网络错误类型扩散细粒度异常分支。
            return AgentReply(output_xml=_text_reply_xml(LLM_FALLBACK_REPLY))


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
