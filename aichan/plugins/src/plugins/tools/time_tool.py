from __future__ import annotations

from dataclasses import dataclass
import datetime

from langchain_core.tools import ArgsSchema, StructuredTool

from plugins.base import ToolPlugin
from pydantic import BaseModel

@dataclass
class CurrentTimeToolPlugin(ToolPlugin):
    """时间工具插件：对外暴露为可绑定的 LLM 工具。"""

    name: str = "get_current_time"
    description: str = "返回当前本地时间。"
    class ToolArgs(BaseModel):
        pass
    args_schema: ArgsSchema = ToolArgs

    def get_current_time(self) -> str:
        """返回当前本地时间。"""
        return f"现在是 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def get_tool(self) -> StructuredTool:
        """返回给 LLM 的工具 schema。"""
        return StructuredTool.from_function(
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
            func=self.get_current_time,
        )
