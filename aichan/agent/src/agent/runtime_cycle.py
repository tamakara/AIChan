from __future__ import annotations

import time

from core.logger import logger, render_panel
from mcp_hub import MCPManager

from .runtime_context import build_context_messages
from .runtime_graph import ReasoningGraphRunner
from .runtime_rules import RuntimeRulesAuditor


class RuntimeCycleRunner:
    """
    负责执行单次唤醒后的推理闭环。

    闭环步骤：
    1. 读取工具快照；
    2. 构造上下文并执行图推理；
    3. 执行首步 fetch 硬约束审计；
    4. 汇总 send 调用或记录内心独白。
    """

    def __init__(
        self,
        *,
        mcp_manager: MCPManager,
        graph_runner: ReasoningGraphRunner,
        rules_auditor: RuntimeRulesAuditor,
    ) -> None:
        # 提供工具快照、唤醒信号等运行时依赖。
        self._mcp_manager = mcp_manager

        # 负责 LLM + Tool 图执行。
        self._graph_runner = graph_runner

        # 负责规则审计与消息提取。
        self._rules_auditor = rules_auditor

    async def run_single_cycle(self) -> None:
        """执行一轮完整唤醒处理。"""
        # 本轮固定使用当前快照，不在周期内刷新工具，避免推理过程工具集合抖动。
        tools = await self._mcp_manager.get_all_tools(refresh=False)
        if not tools:
            logger.warning("⚠️ [AgentRuntime] 当前无可用工具，跳过本轮唤醒")
            return

        # 从工具集合提取“必须在首步调用”的 fetch 工具。
        required_fetch_tools = self._rules_auditor.collect_required_fetch_tools(tools)
        if not required_fetch_tools:
            raise RuntimeError("当前工具集中不存在 fetch_unread_messages，无法执行唤醒流程")
        logger.info(
            "🧭 [AgentRuntime] 本轮首步需全量拉取 fetch 工具: {}",
            ", ".join(sorted(required_fetch_tools)),
        )

        # 构建本轮模型输入上下文。
        prompt_messages = build_context_messages(
            wakeup_signal=self._mcp_manager.get_last_wakeup_signal()
        )

        # 记录单轮总耗时（毫秒）。
        started_at = time.perf_counter()

        # 执行 reason/tools 图并收敛最终消息轨迹。
        all_messages = await self._graph_runner.run_cycle(
            tools=tools,
            prompt_messages=prompt_messages,
        )

        # 硬约束：首条工具调用必须覆盖全部 fetch_unread_messages。
        self._rules_auditor.ensure_first_step_fetch(
            messages=all_messages,
            required_fetch_tools=required_fetch_tools,
        )
        logger.info("✅ [AgentRuntime] 首步全量 fetch_unread_messages 审计通过")

        # 统计本轮所有 send 工具调用。
        send_tool_names = self._rules_auditor.collect_send_tool_calls(all_messages)
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        if not send_tool_names:
            # 无 send 调用时仅记录内心独白，不产生用户可见输出。
            monologue = self._rules_auditor.extract_inner_monologue(all_messages)
            logger.info(
                "🧠 [AgentRuntime] 本轮无 send 工具调用，仅记录内心独白。耗时={}ms\n{}",
                elapsed_ms,
                render_panel(monologue),
            )
            return

        # 有 send 调用即视为本轮对外动作成功完成。
        logger.info(
            "✅ [AgentRuntime] 本轮完成，send 工具调用数={}，工具={}，耗时={}ms",
            len(send_tool_names),
            ", ".join(send_tool_names),
            elapsed_ms,
        )
