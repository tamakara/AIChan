from __future__ import annotations

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from mcp_hub import WakeupSignal

from agent.prompt_templates import EXECUTION_NOTE, SYSTEM_PROMPT


def build_context_messages(wakeup_signal: WakeupSignal | None) -> list[BaseMessage]:
    """
    构建一轮推理所需的上下文消息。

    输出结构：
    1. SystemMessage：固定系统规则；
    2. HumanMessage：本轮唤醒上下文 JSON。
    """
    # 把唤醒信号规范化为可序列化 payload，供模型读取。
    payload = {
        "wakeup_signal": (
            {
                "server_name": wakeup_signal.server_name,
                "resource_uri": wakeup_signal.resource_uri,
                "received_at": wakeup_signal.received_at,
            }
            if wakeup_signal is not None
            else None
        ),
        "execution_note": EXECUTION_NOTE,
    }

    # System + Human 双消息结构可最大化兼容当前模型调用链。
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, indent=2)),
    ]
