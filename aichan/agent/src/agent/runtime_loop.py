from __future__ import annotations

import asyncio
from collections.abc import Callable

from core.logger import logger
from mcp_hub import MCPManager

from .runtime_cycle import RuntimeCycleRunner


class RuntimeLoopRunner:
    """
    负责唤醒事件消费与循环调度。

    运行模型：
    1. 阻塞等待 wakeup 事件；
    2. 事件到达后立即 clear；
    3. 执行单轮推理；
    4. 任何单轮异常都被隔离，不影响后续轮次。
    """

    def __init__(
        self,
        *,
        mcp_manager: MCPManager,
        cycle_runner: RuntimeCycleRunner,
    ) -> None:
        # MCP 管理器：提供唤醒事件与工具访问能力。
        self._mcp_manager = mcp_manager

        # 单轮执行器：封装一轮完整推理流程。
        self._cycle_runner = cycle_runner

    async def run(self, *, is_running: Callable[[], bool]) -> None:
        """主循环入口。`is_running` 用于外部控制退出。"""
        while is_running():
            try:
                # 无轮询等待，直到收到 wakeup 事件。
                logger.info("⏳ [AgentRuntime] 等待 MCPHub 唤醒信号")
                await self._mcp_manager.wait_for_wakeup()
                logger.info("🚦 [AgentRuntime] 已接收到唤醒信号，准备消费本轮")

                # 立刻清除事件，避免同一置位被重复消费。
                self._mcp_manager.clear_wakeup_event()
            except asyncio.CancelledError:
                # 取消信号由上层 stop 流程接管。
                raise
            except Exception as exc:
                # 等待阶段异常不应中断总循环，短暂退避后重试。
                logger.error(
                    "❌ [AgentRuntime] 等待唤醒事件失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
                await asyncio.sleep(0.2)
                continue

            try:
                # 执行单次唤醒处理。
                await self._cycle_runner.run_single_cycle()
            except Exception as exc:
                # 单轮失败仅记录，不影响下一次唤醒消费。
                logger.error(
                    "❌ [AgentRuntime] 处理唤醒循环失败: {}: {}",
                    exc.__class__.__name__,
                    exc,
                )
                self._log_runtime_hint_if_known_issue(exc)

    @staticmethod
    def _log_runtime_hint_if_known_issue(exc: Exception) -> None:
        """针对常见上游报错输出可执行的排障提示。"""
        error_text = str(exc)
        if "thought_signature" not in error_text:
            return

        logger.warning(
            "💡 [AgentRuntime] 检测到 Gemini 函数调用 thought_signature 报错。"
            "若你在 docker-compose 中通过 .env 使用 LLM_API_TYPE，"
            "请确认已把 LLM_API_TYPE 传入容器；"
            "若当前走 OpenAI 兼容网关 + Gemini，建议改用 google 客户端链路或切换到不要求 thought_signature 的模型。"
        )
