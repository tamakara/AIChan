from __future__ import annotations

import json

from ..logger import elapsed_ms, start_timer
from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .observability import Observability
from .session import Session, SessionPreempted


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

    def run(
        self,
        session: Session,
        user_message: str,
    ) -> str:
        """在指定 Session 上执行一轮推理循环，返回纯文本回复。

        锁仅在修改 Context 时短暂持有，LLM 调用与工具执行期间不持锁，
        因此同一 session 的新请求可以中断（抢占）当前生成。
        """
        run_started_at = start_timer()

        # 在锁内追加用户消息并递增 generation，拿到当前 run 的"版本号"。
        with session._lock:
            session._context.add_message(role="user", content=user_message)
            session._generation += 1
            my_gen = session._generation

            run_trace = self._observability.start_run(
                agent_id=session.session_id,
                message_count=len(session._context.messages),
                max_turns=self._max_turns,
                agent_metadata=session.metadata,
            )

        try:
            for turn_idx in range(self._max_turns):
                turn = turn_idx + 1

                with session._lock:
                    if session._generation != my_gen:
                        raise SessionPreempted(
                            session.session_id, my_gen, session._generation
                        )
                    input_messages = list(session._context.messages)

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

                with session._lock:
                    if session._generation != my_gen:
                        raise SessionPreempted(
                            session.session_id, my_gen, session._generation
                        )
                    session._context.add_message(
                        role="assistant",
                        content=llm_response.content,
                        tool_calls=llm_response.tool_calls,
                    )

                if llm_response.finish_reason != "tool_calls":
                    if llm_response.finish_reason == "stop":
                        reply = llm_response.content
                        duration_ms = elapsed_ms(run_started_at)
                        with session._lock:
                            if session._generation != my_gen:
                                raise SessionPreempted(
                                    session.session_id, my_gen, session._generation
                                )
                        self._observability.finish_run_success(
                            run=run_trace,
                            output=reply,
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
                        if session._generation != my_gen:
                            raise SessionPreempted(
                                session.session_id, my_gen, session._generation
                            )
                        session._context.add_message(
                            role="tool",
                            content=tool_call_result,
                            tool_call_id=tool_call_id,
                        )

            raise RuntimeError(
                "Agent failed to complete the task within "
                f"{self._max_turns} turns of interaction."
            )
        except SessionPreempted:
            raise
        except Exception as exc:
            duration_ms = elapsed_ms(run_started_at)
            self._observability.finish_run_error(
                run=run_trace,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
