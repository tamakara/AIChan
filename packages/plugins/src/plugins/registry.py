from __future__ import annotations

from langchain_core.tools import StructuredTool

from plugins.base import BasePlugin, ToolPlugin


class PluginRegistry:
    """全局插件注册表：统一管理通道能力与工具能力。"""

    _pool: dict[str, BasePlugin] = {}

    @classmethod
    def register(cls, instance: BasePlugin) -> None:
        """注册一个插件能力到总线。"""
        cls._pool[instance.name] = instance

    @classmethod
    def get(cls, name: str) -> BasePlugin | None:
        """按名称获取已注册插件。"""
        return cls._pool.get(name)

    @classmethod
    def all(cls) -> list[BasePlugin]:
        """返回当前所有已注册插件实例。"""
        return list(cls._pool.values())

    @classmethod
    def all_tools(cls) -> list[StructuredTool]:
        """
        收集所有可供 LLM 绑定的工具能力。

        约定：仅 `ToolPlugin` 需要实现 `get_tool()`。
        """
        tools: list[StructuredTool] = []
        for plugin in cls._pool.values():
            if isinstance(plugin, ToolPlugin):
                tools.append(plugin.get_tool())
        return tools

    @classmethod
    def clear(cls) -> None:
        """清空注册表，常用于服务重启或单元测试隔离。"""
        cls._pool.clear()
