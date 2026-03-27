import time
from typing import Annotated, List, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from core.logger import logger


class BrainState(TypedDict):
    """Brain 在图执行过程中的状态结构。"""

    # add_messages 负责把节点返回的新消息自动追加到历史消息列表。
    messages: Annotated[list[BaseMessage], add_messages]


class Brain:
    """基于 LangGraph 的推理引擎实现。"""

    _SINGLE_THREAD_ID = "default"

    def __init__(self, llm_client, tools: List):
        # 先把工具能力绑定给大模型，便于后续自动触发 tool_calls。
        self.llm = llm_client.bind_tools(tools) if tools else llm_client
        self.tools = tools
        # MemorySaver 用于按 thread_id 存储短期上下文状态。
        self.memory = MemorySaver()
        # 编译图后得到可执行对象，后续 think 中直接调用。
        self.graph = self._build_graph()

    def _build_graph(self):
        """构建并编译推理图：reason -> (tools?) -> reason。"""
        workflow = StateGraph(BrainState)

        def reason_node(state: BrainState):
            # 该节点负责与 LLM 通信，返回一条 AI 消息。
            try:
                logger.info(
                    "🧠 [Brain] reason 节点执行，历史消息数={}",
                    len(state["messages"]),
                )
                response = self.llm.invoke(state["messages"])
                logger.info(
                    "✅ [Brain] reason 节点返回，消息类型={}",
                    response.__class__.__name__,
                )
                return {"messages": [response]}
            except Exception as exc:
                # 发生异常时写日志并返回兜底消息，防止系统崩溃中断。
                logger.exception(
                    "❌ [Brain] reason 节点异常，LLM 调用失败: {}",
                    exc,
                )
                fallback_msg = AIMessage(
                    content="[系统提示] 笨蛋主人！本小姐的大脑节点暂时离线了，快去检查一下 API Key 和模型名称对不对啦！"
                )
                return {"messages": [fallback_msg]}

        workflow.add_node("reason", reason_node)

        # 路由函数用于判断当前是否需要进入工具调用分支。
        def route(state: BrainState):
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

        return workflow.compile(checkpointer=self.memory)

    def think(
        self,
        context_messages: List[BaseMessage],
        trace_id: str | None = None,
    ) -> str:
        """
        执行一次完整推理流程并返回最终文本。

        参数：
        - context_messages: 由 nexus 组装好的上下文消息列表
        """
        effective_trace_id = trace_id or "brain#default"
        started_at = time.perf_counter()
        logger.info(
            "🚀 [Brain] trace_id={} 开始推理流程，输入消息数={}",
            effective_trace_id,
            len(context_messages),
        )

        config: RunnableConfig = {"configurable": {"thread_id": self._SINGLE_THREAD_ID}}
        try:
            events = self.graph.stream(
                {"messages": context_messages}, config, stream_mode="values"
            )
            # stream 返回状态序列，最后一个状态即本轮推理完成态。
            step_count = 0
            final_state: dict[str, list[BaseMessage]] | None = None
            for state in events:
                step_count += 1
                final_state = state
                last_message = state["messages"][-1]
                has_tool_calls = isinstance(last_message, AIMessage) and bool(
                    last_message.tool_calls
                )
                logger.info(
                    "🔄 [Brain] trace_id={} 图状态推进 step={}，last_message_type={}，tool_calls={}",
                    effective_trace_id,
                    step_count,
                    last_message.__class__.__name__,
                    has_tool_calls,
                )

            if final_state is None:
                raise RuntimeError("Brain 推理流程未产出任何状态")

            reply_content = final_state["messages"][-1].content
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "✅ [Brain] trace_id={} 推理完成，步骤数={}，输出长度={}字符，耗时={}ms",
                effective_trace_id,
                step_count,
                len(reply_content),
                elapsed_ms,
            )
            return reply_content
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                "❌ [Brain] trace_id={} 推理失败，耗时={}ms: {}",
                effective_trace_id,
                elapsed_ms,
                exc,
            )
            raise
