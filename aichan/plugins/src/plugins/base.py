from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from langchain_core.tools import ArgsSchema, StructuredTool

from core.entities import ChannelMessage

@dataclass
class BasePlugin(ABC):
    """
    AIChan 插件系统的统一基类。
    """
    name:str
      
@dataclass
class ToolPlugin(BasePlugin):
    """工具插件基类：对外暴露可绑定给 LLM 的工具接口。"""

    description:str
    args_schema:ArgsSchema

    @abstractmethod
    def get_tool(self) -> StructuredTool:
        """返回该工具插件可绑定给 LLM 的工具 schema。"""
        raise NotImplementedError


class ChannelPlugin(BasePlugin):
    """通道插件基类：对外暴露消息拉取与消息发送能力。"""

    @abstractmethod
    def list_messages(self, since_id: int = 0) -> list[ChannelMessage]:
        """返回 `since_id` 之后的消息列表。"""
        raise NotImplementedError

    @abstractmethod
    def send_message(self, role: str, content: str) -> ChannelMessage:
        """向通道写入一条消息并返回写入结果。"""
        raise NotImplementedError
