import json
import time
from typing import Annotated, List, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from core.entities import ChannelMessage
from core.logger import logger, render_panel
from agent.prompt_builder import build_context_messages


class AgentState(TypedDict):
    """Agent 推理图在执行过程中的状态结构。"""

    # add_messages 负责把节点返回的新消息自动追加到历史消息列表。
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
    """渲染完整的 LLM 输入提示词（不截断）。"""
    sections: list[str] = []
    for index, message in enumerate(messages, start=1):
        header = f"[{index}] role={message.type}"
        if message.id:
            header = f"{header} id={message.id}"

        section = f"{header}\n{_serialize_message_content(message.content)}"
        if isinstance(message, AIMessage) and message.tool_calls:
            tool_calls = json.dumps(message.tool_calls, ensure_ascii=False, indent=2)
            section = f"{section}\n\n[tool_calls]\n{tool_calls}"
        sections.append(section)

    return "\n\n".join(sections)


def _extract_tool_names(message: AIMessage) -> list[str]:
    """提取一条 AI 消息中的工具调用名称。"""
    names: list[str] = []
    for tool_call in message.tool_calls:
        names.append(tool_call.get("name", "<unknown_tool>"))
    return names


class Agent:
    """基于 LangGraph 的 Agent 推理引擎。"""

    def __init__(self, llm_client, tools: List):
        # 先把工具能力绑定给大模型，便于后续自动触发 tool_calls。
        self.llm = llm_client.bind_tools(tools) if tools else llm_client
        self.tools = tools
        # 编译图后得到可执行对象，后续 think 中直接调用。
        self.graph = self._build_graph()

    def _build_graph(self):
        """构建并编译推理图：reason -> (tools?) -> reason。"""
        workflow = StateGraph(AgentState)

        def reason_node(state: AgentState):
            # 该节点负责与 LLM 通信，返回一条 AI 消息。
            try:
                logger.info(
                    "🧾 [LLM] 请求提示词:\n{}",
                    render_panel(_render_full_prompt(state["messages"])),
                )
                response = self.llm.invoke(state["messages"])
                if isinstance(response, AIMessage) and response.tool_calls:
                    logger.info(
                        "🛠 [LLM] 调用工具: {}",
                        ", ".join(_extract_tool_names(response)),
                    )
                return {"messages": [response]}
            except Exception as exc:
                # 发生异常时仅记录日志并向上抛出，避免向用户发送失败提示文案。
                logger.error(
                    "❌ [Agent] reason 节点异常，LLM 调用失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
                raise

        workflow.add_node("reason", reason_node)

        # 路由函数用于判断当前是否需要进入工具调用分支。
        def route(state: AgentState):
            last_msg = state["messages"][-1]
            if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
                return "tools"
            return END

        workflow.set_entry_point("reason")
        workflow.add_conditional_edges("reason", route)

        if self.tools:
            # 当存在工具能力时，增加 tools 节点并回到 reason 形成闭环。
            workflow.add_node("tools", ToolNode(self.tools))
            workflow.add_edge("tools", "reason")

        return workflow.compile()

    def think(
        self,
        old_messages: list[ChannelMessage],
        new_messages: list[ChannelMessage],
        trace_id: str | None = None,
    ) -> str:
        """
        执行一次完整推理流程并返回最终文本。

        参数：
        - old_messages: 已处理过的历史消息
        - new_messages: 本次新增消息（只包含增量）
        """
        context_messages = build_context_messages(
            old_messages=old_messages,
            new_messages=new_messages,
        )
        effective_trace_id = trace_id or "agent#default"
        started_at = time.perf_counter()

        try:
            events = self.graph.stream({"messages": context_messages}, stream_mode="values")
            final_state: dict[str, list[BaseMessage]] | None = None
            for state in events:
                final_state = state

            if final_state is None:
                raise RuntimeError("Agent 推理流程未产出任何状态")

            reply_content = final_state["messages"][-1].content
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "✅ [Agent] trace_id={} 推理完成，输出长度={}字符，耗时={}ms",
                effective_trace_id,
                len(reply_content),
                elapsed_ms,
            )
            return reply_content
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.error(
                "❌ [Agent] trace_id={} 推理失败，耗时={}ms: {}: {}",
                effective_trace_id,
                elapsed_ms,
                exc.__class__.__name__,
                exc,
            )
            raise
