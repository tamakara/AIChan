from __future__ import annotations

import asyncio
from typing import Any

from .models import GatewayConfig

# 全局事件总线：网关 SSE 收到的 message 事件统一写入该队列。
global_event_bus: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
# 动态工具注册表：键为网关名，值为该网关映射出的工具集合与元数据。
gateway_tools_registry: dict[str, dict[str, Any]] = {}
# 网关配置注册表：供 SignalProcessor 和事件触发器查询网关连接信息与类型。
gateway_config_registry: dict[str, GatewayConfig] = {}
# 网关后台接入任务表：同名网关重复注册时可安全替换旧任务。
gateway_onboarding_tasks: dict[str, asyncio.Task[Any]] = {}
