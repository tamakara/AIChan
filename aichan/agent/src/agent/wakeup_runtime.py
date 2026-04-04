from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Annotated, Any, Callable, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from core.logger import logger, render_panel
from mcp_hub import MCPManager, WakeUpEvent

from agent.prompt_templates import TOOL_AS_ACTION_SYSTEM_PROMPT


class RuntimeState(TypedDict):
    """WakeUpAgentRuntime 图状态。"""

    messages: Annotated[list[BaseMessage], add_messages]


def _serialize_message_content(content: object) -> str:
    """将消息内容稳定序列化为日志文本。"""
    if isinstance(content, str):
        return content

    try:
        return json.dumps(content, ensure_ascii=False, indent=2)
    except TypeError:
        return repr(content)


def _render_full_prompt(messages: list[BaseMessage]) -> str:
    """渲染完整模型输入，便于追踪 Tool-as-Action 执行链。"""
    sections: list[str] = []
    for index, message in enumerate(messages, start=1):
        header = f"[{index}] role={message.type}"
        if message.id:
            header = f"{header} id={message.id}"

        section = f"{header}\n{_serialize_message_content(message.content)}"
        if isinstance(message, AIMessage) and message.tool_calls:
            section = (
                f"{section}\n\n[tool_calls]\n"
                f"{json.dumps(message.tool_calls, ensure_ascii=False, indent=2)}"
            )
        sections.append(section)

    return "\n\n".join(sections)


class WakeUpAgentRuntime:
    """
    Agent 唤醒执行器（Pull + Tool-as-Action）。

    主流程：
    1. 监听 MCPHub 的 WakeUpEvent；
    2. 合并短时间内积压事件；
    3. 运行 LLM + Tool 循环；
    4. 仅把普通文本记录为内心独白，用户可见输出必须来自 send_* 工具副作用。
    """

    def __init__(
        self,
        *,
        llm_factory: Callable[[], Any],
        mcp_manager: MCPManager,
    ) -> None:
        self._llm_factory = llm_factory
        self._mcp_manager = mcp_manager
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """启动后台唤醒循环。"""
        if self._running:
            logger.warning("♻️ [WakeUpRuntime] 已在运行，忽略重复启动")
            return

        self._running = True
        self._worker_task = asyncio.create_task(
            self._run_loop(),
            name="wakeup-agent-runtime",
        )
        logger.info("🟢 [WakeUpRuntime] 唤醒运行时已启动")

    async def stop(self) -> None:
        """停止后台唤醒循环。"""
        task = self._worker_task
        self._running = False
        self._worker_task = None
        if task is None:
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🛑 [WakeUpRuntime] 唤醒运行时已停止")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                first_event = await self._mcp_manager.wait_wakeup_event(timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                logger.error(
                    "❌ [WakeUpRuntime] 等待唤醒事件失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
                await asyncio.sleep(0.2)
                continue

            coalesced_events = [first_event, *self._mcp_manager.drain_pending_wakeup_events()]
            try:
                await self._run_single_cycle(events=coalesced_events)
            except Exception as exc:
                logger.error(
                    "❌ [WakeUpRuntime] 处理唤醒批次失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )

    async def _run_single_cycle(self, events: list[WakeUpEvent]) -> None:
        """执行一次唤醒推理循环。"""
        if not events:
            return

        tools = await self._mcp_manager.get_all_tools(refresh=False)
        if not tools:
            logger.warning("⚠️ [WakeUpRuntime] 当前无可用工具，跳过本轮唤醒")
            return

        graph = self._build_graph(tools=tools)
        prompt_messages = self._build_context_messages(events=events)
        started_at = time.perf_counter()

        final_state: dict[str, list[BaseMessage]] | None = None
        async for state in graph.astream({"messages": prompt_messages}, stream_mode="values"):
            final_state = state

        if final_state is None:
            raise RuntimeError("推理流程未产出任何状态")

        all_messages = final_state["messages"]
        send_tool_names = self._collect_send_tool_calls(all_messages)
        first_tool_call_names = self._first_tool_call_names(all_messages)
        if not self._is_first_step_fetch(first_tool_call_names):
            logger.warning(
                "⚠️ [WakeUpRuntime] 首次工具调用未满足 fetch_unread_messages 约束，calls={}",
                first_tool_call_names,
            )

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if not send_tool_names:
            monologue = self._extract_inner_monologue(all_messages)
            logger.info(
                "🧠 [WakeUpRuntime] 本轮无 send_* 工具调用，仅记录内心独白。耗时={}ms\n{}",
                elapsed_ms,
                render_panel(monologue),
            )
            return

        logger.info(
            "✅ [WakeUpRuntime] 本轮完成，send 工具调用数={}，工具={}，耗时={}ms",
            len(send_tool_names),
            ", ".join(send_tool_names),
            elapsed_ms,
        )

    def _build_graph(self, tools: list[BaseTool]):
        llm = self._llm_factory()
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        workflow = StateGraph(RuntimeState)

        async def reason_node(state: RuntimeState):
            logger.info(
                "🧾 [WakeUpRuntime] LLM 输入:\n{}",
                render_panel(_render_full_prompt(state["messages"])),
            )
            response = await llm_with_tools.ainvoke(state["messages"])
            if isinstance(response, AIMessage) and response.tool_calls:
                called_tools = [
                    str(item.get("name", "<unknown_tool>"))
                    for item in response.tool_calls
                ]
                logger.info("🛠 [WakeUpRuntime] LLM 请求工具: {}", ", ".join(called_tools))
            return {"messages": [response]}

        def route(state: RuntimeState):
            last_message = state["messages"][-1]
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                return "tools"
            return END

        workflow.add_node("reason", reason_node)
        workflow.set_entry_point("reason")
        workflow.add_conditional_edges("reason", route)
        workflow.add_node("tools", ToolNode(tools))
        workflow.add_edge("tools", "reason")
        return workflow.compile()

    @staticmethod
    def _build_context_messages(events: list[WakeUpEvent]) -> list[BaseMessage]:
        payload = {
            "wakeup_batch_size": len(events),
            "wakeup_events": [
                {
                    "server_name": event.server_name,
                    "event": event.event,
                    "channel": event.channel,
                    "message_id": event.message_id,
                    "received_at": event.received_at,
                }
                for event in events
            ],
            "execution_note": (
                "你已被外部消息唤醒。请严格遵守系统规则，"
                "先调用所有 fetch_unread_messages 工具；如需上下文可再调用 fetch_message_history。"
            ),
        }
        return [
            SystemMessage(content=TOOL_AS_ACTION_SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
        ]

    @staticmethod
    def _collect_send_tool_calls(messages: list[BaseMessage]) -> list[str]:
        """提取所有 send_{channel}_message 工具调用名。"""
        send_tools: list[str] = []
        server_tool_pattern = re.compile(r".*__send_[A-Za-z0-9_]+_message$")
        plain_tool_pattern = re.compile(r"^send_[A-Za-z0-9_]+_message$")
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            for tool_call in message.tool_calls:
                tool_name = str(tool_call.get("name", "")).strip()
                if server_tool_pattern.match(tool_name) or plain_tool_pattern.match(tool_name):
                    send_tools.append(tool_name)
        return send_tools

    @staticmethod
    def _first_tool_call_names(messages: list[BaseMessage]) -> list[str]:
        """获取第一条带工具调用 AI 消息中的全部工具名。"""
        for message in messages:
            if not isinstance(message, AIMessage):
                continue
            if not message.tool_calls:
                continue
            return [str(tool.get("name", "")).strip() for tool in message.tool_calls]
        return []

    @staticmethod
    def _is_first_step_fetch(first_tool_call_names: list[str]) -> bool:
        if not first_tool_call_names:
            return False
        for name in first_tool_call_names:
            if name.endswith("__fetch_unread_messages"):
                return True
        return False

    @staticmethod
    def _extract_inner_monologue(messages: list[BaseMessage]) -> str:
        """提取最终 AI 文本输出作为内心独白。"""
        for message in reversed(messages):
            if not isinstance(message, AIMessage):
                continue
            if message.tool_calls:
                continue
            content = message.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            return _serialize_message_content(content)
        return "[empty inner monologue]"
