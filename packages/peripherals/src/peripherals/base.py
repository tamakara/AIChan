from __future__ import annotations

from abc import ABC
from typing import Any


class BasePeripheral(ABC):
    """外设抽象基类：所有外设能力（通道/工具）都应继承此类。"""

    def __init__(self, name: str) -> None:
        # name 作为注册表中的唯一能力标识。
        self.name = name

    def to_tool_schema(self) -> Any:
        """
        返回可供 LLM 绑定的工具 schema。

        默认返回 None，表示该外设不是可调用工具（例如纯输入通道）。
        """
        return None
