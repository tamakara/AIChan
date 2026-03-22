from __future__ import annotations

import datetime

from langchain_core.tools import tool

from peripherals.base import BasePeripheral


@tool
def get_current_time() -> str:
    """返回当前本地时间。"""
    return f"现在是 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"


class CurrentTimeToolPeripheral(BasePeripheral):
    """时间工具外设：对外暴露为可绑定的 LLM 工具。"""

    def __init__(self, name: str = "get_current_time") -> None:
        super().__init__(name=name)

    def to_tool_schema(self):
        """返回给 LLM 的工具 schema。"""
        return get_current_time
