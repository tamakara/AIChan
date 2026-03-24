from typing import Annotated, TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, AIMessage

from core.logger import logger

from core.interfaces import IReasoningEngine
from langchain_core.runnables import RunnableConfig


class BrainState(TypedDict):
    """Brain 在图执行过程中的状态结构。"""

    # add_messages 负责把节点返回的新消息自动追加到历史消息列表。
    messages: Annotated[list[BaseMessage], add_messages]


class Brain(IReasoningEngine):
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
                logger.info("🧠 正在向大脑节点发送神经信号...")
                response = self.llm.invoke(state["messages"])
                logger.info("✅ 脑波接收成功！")
                return {"messages": [response]}
            except Exception as e:
                # 发生异常时写日志并返回兜底消息，防止系统崩溃中断。
                logger.error(f"❌ 大脑神经元连接断开 (LLM调用失败): {str(e)}")
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

    def think(self, context_messages: List[BaseMessage]) -> str:
        """
        执行一次完整推理流程并返回最终文本。

        参数：
        - context_messages: 由 nexus 组装好的上下文消息列表
        """
        config: RunnableConfig = {"configurable": {"thread_id": self._SINGLE_THREAD_ID}}

        events = self.graph.stream(
            {"messages": context_messages}, config, stream_mode="values"
        )
        # stream 返回状态序列，最后一个状态即本轮推理完成态。
        final_state = list(events)[-1]
        return final_state["messages"][-1].content

