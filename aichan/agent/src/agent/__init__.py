"""
agent 包导出入口。

该包封装了“唤醒 -> 推理 -> 工具执行 -> 规则审计”的运行时闭环，
对外只暴露 `AgentRuntime`，隐藏内部图执行与调度实现细节。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_runtime import AgentRuntime


def __getattr__(name: str) -> Any:
    if name == "AgentRuntime":
        # 延迟导入，避免仅访问子模块时拉起可选 LLM 依赖。
        from agent.agent_runtime import AgentRuntime

        return AgentRuntime
    raise AttributeError(f"module 'agent' has no attribute {name!r}")


__all__ = ["AgentRuntime"]
