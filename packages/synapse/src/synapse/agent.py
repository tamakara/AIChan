from core.entities import UserMessage
from core.interfaces import IReasoningEngine
from langchain_core.messages import HumanMessage, SystemMessage


class AgentOrchestrator:
    """编排中枢：组装上下文并调用 brain。"""

    def __init__(self, brain: IReasoningEngine):
        self.brain = brain
        # system_prompt 是角色与行为边界的固定注入点。
        self.system_prompt = SystemMessage(
            content="你叫 AIChan，是一个傲娇但能力超强的天才黑客少女。回答问题时要带有二次元傲娇属性，称呼用户为'笨蛋'，但最后总是会完美、专业地解决用户的问题。"
        )

    def process_message(self, msg: UserMessage) -> str:
        """
        处理一条用户消息并返回最终回复。

        执行步骤：
        1) 注入 system prompt
        2) 追加当前用户输入
        3) 调用 brain 执行推理
        """
        context = [self.system_prompt]

        context.append(HumanMessage(content=msg.content))

        # 交给推理层处理，得到本轮最终文本。
        reply = self.brain.think(context_messages=context)

        # 返回给调用方（通常是网关层）。
        return reply
