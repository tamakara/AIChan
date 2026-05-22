from __future__ import annotations

import json
from threading import Lock
from typing import Any
from uuid import uuid4

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .observability import Observability
from .prompts import SYSTEM_PROMPT
from .tag_builder import build_session_start_tag
from .types.context import Context
from .types.llm import Message


class Agent:
    def __init__(
        self,
        agent_id: str,
        llm_client: LlmClient,
        mcp_gateway: McpGateway,
        max_turns: int,
        temperature: float,
        metadata: dict[str, Any],
        observability: Observability,
    ) -> None:
        self._logger = get_logger("agent")
        self._agent_id = agent_id
        self._metadata = dict(metadata)
        self._llm_client = llm_client
        self._mcp_gateway = mcp_gateway
        self._max_turns = max_turns
        self._temperature = temperature
        self._observability = observability
        self._lock = Lock()
        self._context = Context()
        self._context.add_message(role="system", content=SYSTEM_PROMPT)
        self._context.add_message(
            role="system",
            content=build_session_start_tag(
                agent_id=agent_id,
                metadata=self._metadata,
            ),
        )

    def run(self, user_message: str, message_count: int) -> str:
        run_started_at = start_timer()
        with self._lock:
            # 把日志与消息写入放在同一把会话锁内，确保日志时间线与上下文状态严格一致。
            log_info(
                self._logger,
                "agent.run_started",
                agent_id=self._agent_id,
                max_turns=self._max_turns,
                message_len=len(user_message),
            )
            run_trace = self._observability.start_run(
                agent_id=self._agent_id,
                message_count=message_count,
                max_turns=self._max_turns,
                agent_metadata=self._metadata,
            )
            self._context.add_message(role="user", content=user_message)
            try:
                for turn_idx in range(self._max_turns):
                    turn = turn_idx + 1
                    input_messages = list(self._context.messages)

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

                    self._context.add_message(
                        role="assistant",
                        content=llm_response.content,
                        tool_calls=llm_response.tool_calls,
                    )

                    if llm_response.finish_reason != "tool_calls":
                        if llm_response.finish_reason == "stop":
                            reply = llm_response.content
                            duration_ms = elapsed_ms(run_started_at)
                            self._observability.finish_run_success(
                                run=run_trace,
                                reply=reply,
                                duration_ms=duration_ms,
                            )
                            log_info(
                                self._logger,
                                "agent.run_completed",
                                agent_id=self._agent_id,
                                reply_len=len(reply),
                                elapsed_ms=duration_ms,
                            )
                            return reply
                        raise RuntimeError(
                            "LLM response ended with unexpected reason: "
                            f"{llm_response.finish_reason}"
                        )

                    # 工具调用结果必须写回上下文，再进入下一轮 LLM，确保模型拥有完整推理链路。
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

                        self._context.add_message(
                            role="tool",
                            content=tool_call_result,
                            tool_call_id=tool_call_id,
                        )

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
                log_exception(
                    self._logger,
                    "agent.run_failed",
                    agent_id=self._agent_id,
                    elapsed_ms=duration_ms,
                )
                raise

    def get_agent_id(self) -> str:
        return self._agent_id

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def get_messages(self) -> list[Message]:
        return self._context.messages


class AgentRegistry:
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
        self._agents: dict[str, Agent] = {}
        self._lock = Lock()

    def create(self, metadata: dict[str, Any]) -> Agent:
        with self._lock:
            agent_id = str(uuid4())
            agent = Agent(
                agent_id=agent_id,
                llm_client=self._llm_client,
                mcp_gateway=self._mcp_gateway,
                max_turns=self._max_turns,
                temperature=self._temperature,
                metadata=metadata,
                observability=self._observability,
            )
            self._agents[agent_id] = agent
            return agent

    def get(self, agent_id: str) -> Agent | None:
        with self._lock:
            return self._agents.get(agent_id)

