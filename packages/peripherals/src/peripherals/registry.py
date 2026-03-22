from __future__ import annotations

from typing import Any

from peripherals.base import BasePeripheral


class PeripheralRegistry:
    """全局外设注册表：统一管理通道能力与工具能力。"""

    _pool: dict[str, BasePeripheral] = {}

    @classmethod
    def register(cls, name: str, instance: BasePeripheral) -> None:
        """注册一个外设能力到总线。"""
        cls._pool[name] = instance

    @classmethod
    def get(cls, name: str) -> BasePeripheral | None:
        """按名称获取已注册外设。"""
        return cls._pool.get(name)

    @classmethod
    def all_tools(cls) -> list[Any]:
        """
        收集所有可供 LLM 绑定的工具能力。

        约定：仅当外设实现了 `to_tool_schema()` 且返回非 None 时，才视为工具。
        """
        tools: list[Any] = []
        for peripheral in cls._pool.values():
            tool_schema = peripheral.to_tool_schema()
            if tool_schema is not None:
                tools.append(tool_schema)
        return tools

    @classmethod
    def clear(cls) -> None:
        """清空注册表，常用于服务重启或单元测试隔离。"""
        cls._pool.clear()
