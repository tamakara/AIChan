from __future__ import annotations

import asyncio
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from core.logger import logger
from mcp_hub import MCPManager
from pydantic import SecretStr

from .runtime_cycle import RuntimeCycleRunner
from .runtime_graph import ReasoningGraphRunner
from .runtime_loop import RuntimeLoopRunner
from .runtime_rules import RuntimeRulesAuditor


class AgentRuntime:
    """
    Agent 唤醒执行器（Pull + Tool-as-Action）。

    主流程：
    1. 挂起等待 MCPHub 全局唤醒事件；
    2. 唤醒后立即 clear 事件标记；
    3. 运行 LLM + Tool 循环；
    4. 仅把普通文本记录为内心独白，用户可见输出必须来自 send 工具副作用。
    """

    def __init__(
        self,
        *,
        llm_api_type: Literal["openai", "google"],
        llm_api_key: SecretStr,
        llm_base_url: str,
        llm_model_name: str,
        llm_temperature: float,
        mcp_manager: MCPManager,
    ) -> None:
        # 后台工作任务句柄；运行中为 asyncio.Task，停止后为 None。
        self._worker_task: asyncio.Task[None] | None = None

        # 运行状态位，控制主循环是否继续消费唤醒事件。
        self._running = False

        # LLM 配置由 main 注入，具体客户端在运行时内部构建。
        self._llm_api_type = llm_api_type
        self._llm_api_key = llm_api_key
        self._llm_base_url = llm_base_url
        self._llm_model_name = llm_model_name
        self._llm_temperature = llm_temperature

        # 图执行器：负责 reason/tools 图的构建与执行。
        graph_runner = ReasoningGraphRunner(llm_factory=self._build_llm_client)

        # 规则审计器：负责首步 fetch 与 send 工具规则校验。
        rules_auditor = RuntimeRulesAuditor()

        # 单轮执行器：把“拉工具 -> 跑图 -> 审计 -> 记录结果”封装为一个动作。
        cycle_runner = RuntimeCycleRunner(
            mcp_manager=mcp_manager,
            graph_runner=graph_runner,
            rules_auditor=rules_auditor,
        )

        # 循环调度器：负责“等待唤醒 -> 执行单轮 -> 异常隔离”。
        self._loop_runner = RuntimeLoopRunner(
            mcp_manager=mcp_manager,
            cycle_runner=cycle_runner,
        )

    async def start(self) -> None:
        """启动后台唤醒循环。"""
        if self._running:
            logger.warning("♻️ [AgentRuntime] 已在运行，忽略重复启动")
            return

        # 先置位运行状态，再创建后台循环任务。
        self._running = True
        self._worker_task = asyncio.create_task(
            self._run_loop(),
            name="agent-runtime",
        )
        logger.info("🟢 [AgentRuntime] 唤醒运行时已启动")

    async def stop(self) -> None:
        """停止后台唤醒循环。"""
        task = self._worker_task

        # 先关闭运行标志，阻止新循环继续执行。
        self._running = False
        self._worker_task = None
        if task is None:
            return

        # 主动取消后台任务并等待其退出。
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logger.info("🛑 [AgentRuntime] 唤醒运行时已停止")

    async def _run_loop(self) -> None:
        """委托循环调度器执行主循环。"""
        await self._loop_runner.run(is_running=self._is_running)

    def _is_running(self) -> bool:
        """提供给调度器的运行状态读取回调。"""
        return self._running

    def _build_llm_client(self) -> BaseChatModel:
        """
        根据 API 类型构建实际 LLM 客户端。

        - openai: 使用 ChatOpenAI；
        - google: 使用 ChatGoogleGenerativeAI。
        """
        if self._llm_api_type == "openai":
            return ChatOpenAI(
                api_key=self._llm_api_key,
                base_url=self._llm_base_url,
                model=self._llm_model_name,
                temperature=self._llm_temperature,
            )

        if self._llm_api_type == "google":
            return ChatGoogleGenerativeAI(
                model=self._llm_model_name,
                google_api_key=self._llm_api_key,
                base_url=self._llm_base_url,
                temperature=self._llm_temperature,
            )

        raise ValueError(f"不支持的 llm_api_type: {self._llm_api_type}")
