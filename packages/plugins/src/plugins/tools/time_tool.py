from __future__ import annotations

import datetime

from langchain_core.tools import StructuredTool

from plugins.base import BaseToolPlugin


class CurrentTimeToolPlugin(BaseToolPlugin):
    """时间工具插件：对外暴露为可绑定的 LLM 工具。"""

    def __init__(
        self,
        name: str = "get_current_time",
        description: str = "返回当前本地时间。",
    ) -> None:
        super().__init__(name=name, description=description)

    def get_current_time(self) -> str:
        """返回当前本地时间。"""
        return f"现在是 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    def get_tool(self) -> StructuredTool:
        """返回给 LLM 的工具 schema。"""
        return StructuredTool.from_function(
            func=self.get_current_time,
            name=self.name,
            description=self.description,
        )
