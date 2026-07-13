from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..adapters.registry import AdapterRegistry
from ..adapters.xml_codec import XmlMessageCodec
from ..logger import elapsed_ms, start_timer
from .context_manager import ContextManager
from .builtin_tools import BuiltinTools
from .llm_client import LlmClient
from .observability import Observability, RunTrace
from .types.llm import LlmResponse, Message, ToolCall

LLM_FALLBACK_REPLY = "笨蛋，刚才脑袋短路了一下，稍后再试试喵。"


@dataclass(frozen=True)
class AgentReply:
    reply_xml: str
    allowed_file_refs: frozenset[str]


class Agent:
    def __init__(self, *, llm_client: LlmClient, builtin_tools: BuiltinTools, adapters: AdapterRegistry, contexts: ContextManager, codec: XmlMessageCodec, max_turns: int, max_retries: int, temperature: float, observability: Observability) -> None:
        self._llm = llm_client
        self._builtin_tools = builtin_tools
        self._adapters = adapters
        self._contexts = contexts
        self._codec = codec
        self._max_turns = max_turns
        self._max_retries = max_retries
        self._temperature = temperature
        self._observability = observability

    async def run(self, *, session_id: str, adapter_key: tuple[str, str], messages_xml: str, file_refs: frozenset[str]) -> AgentReply:
        started = start_timer()
        await self._contexts.add_file_refs(session_id, file_refs)
        staged: list[Message] = []
        pending = [messages_xml]
        registration = self._adapters.registration(adapter_key)
        snapshot = await self._contexts.snapshot(session_id, [], registration.skills)
        trace = self._observability.start_run(session_id=session_id, message_count=len(snapshot.messages) + 1, max_turns=self._max_turns, agent_metadata=snapshot.metadata)
        try:
            for turn in range(1, self._max_turns + 1):
                _stage(staged, "system", f'<turn index="{turn}" />')
                for item in pending:
                    _stage(staged, "user", item)
                pending = []
                registration = self._adapters.registration(adapter_key)
                snapshot = await self._contexts.snapshot(session_id, staged, registration.skills)
                tools = [*self._builtin_tools.schemas(), *self._adapters.tool_schemas(adapter_key)]
                response = await self._generate(trace, turn, snapshot.messages, tools, registration, snapshot.allowed_file_refs)
                if response.finish_reason == "stop":
                    _stage(staged, "assistant", response.content)
                    queued = await self._contexts.commit_if_no_queue(session_id, staged)
                    if queued:
                        staged.pop()
                        pending = queued
                        continue
                    final_snapshot = await self._contexts.snapshot(session_id, [], registration.skills)
                    self._observability.finish_run_success(run=trace, output={"reply_xml": response.content}, duration_ms=elapsed_ms(started))
                    return AgentReply(response.content, final_snapshot.allowed_file_refs)

                _stage(staged, "assistant", response.content, tool_calls=response.tool_calls)
                for tool_call in response.tool_calls:
                    result = await self._call_tool(trace, turn, session_id, adapter_key, snapshot.metadata, tool_call)
                    _stage(staged, "tool", result, tool_call_id=tool_call.id)
                pending = await self._contexts.drain_queued(session_id)
            raise RuntimeError(f"Agent 在 {self._max_turns} 轮内未完成")
        except Exception as exc:
            self._observability.finish_run_error(run=trace, error=str(exc), duration_ms=elapsed_ms(started))
            fallback = self._codec.text_reply(LLM_FALLBACK_REPLY)
            _stage(staged, "assistant", fallback)
            await self._contexts.commit(session_id, staged)
            final_snapshot = await self._contexts.snapshot(session_id, [], registration.skills)
            return AgentReply(fallback, final_snapshot.allowed_file_refs)

    async def _generate(self, trace: RunTrace, turn: int, messages: list[Message], tools: list[dict[str, Any]], registration: Any, allowed_keys: frozenset[str]) -> LlmResponse:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                started = start_timer()
                response = await self._llm.generate(messages, tools, self._temperature)
                self._observability.llm_generation(run=trace, turn=turn, input_messages=messages, output_content=response.content, output_tool_calls=response.tool_calls, finish_reason=response.finish_reason, model=self._llm.model_name, duration_ms=elapsed_ms(started))
                if response.finish_reason == "tool_calls":
                    return response
                if response.finish_reason != "stop":
                    raise RuntimeError(f"unexpected finish reason: {response.finish_reason}")
                normalized = self._codec.validate_reply(response.content, registration, allowed_keys)
                return response.model_copy(update={"content": normalized.xml})
            except Exception as exc:
                last_error = exc
                if attempt >= self._max_retries:
                    raise
        raise RuntimeError("LLM retry loop exited") from last_error

    async def _call_tool(self, trace: RunTrace, turn: int, session_id: str, adapter_key: tuple[str, str], metadata: dict[str, Any], tool_call: ToolCall) -> str:
        started = start_timer()
        name = tool_call.function.name
        raw_arguments = tool_call.function.arguments
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise TypeError("工具参数必须是对象")
            if name in {item["function"]["name"] for item in self._adapters.tool_schemas(adapter_key)}:
                value = await self._adapters.invoke(adapter_key, session_id, name, arguments)
            else:
                value = await self._builtin_tools.call(name=name, arguments=arguments, session_id=session_id, adapter_key=adapter_key, metadata=metadata)
            result = json.dumps(value, ensure_ascii=False)
            self._observability.tool_span(run=trace, turn=turn, tool_name=name, tool_args=arguments, status="ok", error=None, duration_ms=elapsed_ms(started), output=result)
            return result
        except Exception as exc:
            result = json.dumps({"error": f"tool `{name}` failed: {exc}"}, ensure_ascii=False)
            self._observability.tool_span(run=trace, turn=turn, tool_name=name, tool_args={"raw_arguments": str(raw_arguments)}, status="failed", error=str(exc), duration_ms=elapsed_ms(started), output=result)
            return result


def _stage(messages: list[Message], role: str, content: str, *, tool_calls: list[ToolCall] | None = None, tool_call_id: str | None = None) -> None:
    item: dict[str, Any] = {"role": role, "content": content}
    if role == "assistant" and tool_calls is not None:
        item["tool_calls"] = tool_calls
    if role == "tool" and tool_call_id is not None:
        item["tool_call_id"] = tool_call_id
    messages.append(item)  # type: ignore[arg-type]
