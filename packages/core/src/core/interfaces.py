from abc import ABC, abstractmethod
from typing import List
from langchain_core.messages import BaseMessage


class IReasoningEngine(ABC):
    """推理引擎契约：定义 brain 对外必须实现的统一方法。"""

    @abstractmethod
    def think(self, context_messages: List[BaseMessage]) -> str:
        """
        基于上下文执行推理并返回最终文本。

        参数：
        - context_messages: 由编排层组织后的消息列表
        """
        pass
