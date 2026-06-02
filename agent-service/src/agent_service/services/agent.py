from __future__ import annotations

import json

from ..logger import elapsed_ms, start_timer
from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .observability import Observability
from .session import Session


class Agent:
    """可复用的 Agent 单例，对 Session 执行推理。

    Agent 持有共享的 LLM 客户端、MCP 网关与可观测性实例，
    通过 run(session, ...) 在指定会话上执行 turn-loop，返回纯文本回复。
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

    def run(self, session: Session, user_message: str) -> str:
        """在指定 Session 上执行一轮推理循环，返回纯文本回复。"""
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

                # 2a. 锁内快照当前上下文
                with session._lock:
                    input_messages = list(session._context.messages)

                # 2b. LLM 调用（不持锁）
                llm_started_at = start_timer()
                llm_response = self._llm_client.generate(
                    messages=input_messages,
                    tools_schema=self._mcp_gateway.get_tools_schema(),
                    temperature=self._temperature,
                )
                llm_elapsed_ms = elapsed_ms(llm_started_at)

                # 2c. 记录本次 LLM 调用
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

                # 2d. 锁内写入 assistant 消息
                with session._lock:
                    session._context.add_message(
                        role="assistant",
                        content=llm_response.content,
                        tool_calls=llm_response.tool_calls,
                    )

                # 2e. 判断 finish_reason 分支
                if llm_response.finish_reason != "tool_calls":
                    # stop 表示 LLM 认为推理完成，返回纯文本
                    if llm_response.finish_reason == "stop":
                        reply = llm_response.content
                        duration_ms = elapsed_ms(run_started_at)
                        self._observability.finish_run_success(
                            run=run_trace,
                            output=reply,
                            duration_ms=duration_ms,
                        )
                        return reply
                    # 其他 finish_reason（length/content_filter 等）视为异常
                    raise RuntimeError(
                        "LLM response ended with unexpected reason: "
                        f"{llm_response.finish_reason}"
                    )

                # 2f. tool_calls 分支：依次执行工具，失败不中断回合
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
                        # 工具调用异常写回 tool 错误消息，让 LLM 自行修正
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

                    # 锁内写入 tool 结果消息
                    with session._lock:
                        session._context.add_message(
                            role="tool",
                            content=tool_call_result,
                            tool_call_id=tool_call_id,
                        )

            # ── 3. 超过 max_turns 仍未 stop ──
            raise RuntimeError(
                "Agent failed to complete the task within "
                f"{self._max_turns} turns of interaction."
            )
        except Exception as exc:
            # ── 4. 异常收尾：记录观测失败状态后重新抛出 ──
            duration_ms = elapsed_ms(run_started_at)
            self._observability.finish_run_error(
                run=run_trace,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
