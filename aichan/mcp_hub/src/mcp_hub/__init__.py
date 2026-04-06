"""
MCP Hub 包导出入口。

外部模块通常只需要导入：
1. `MCPManager` 作为统一连接与工具编排入口；
2. `WakeupSignal` 用于读取最近一次唤醒上下文。
"""

from mcp_hub.manager import MCPManager
from mcp_hub.models import WakeupSignal

__all__ = [
    "MCPManager",
    "WakeupSignal",
]
