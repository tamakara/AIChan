from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from core.logger import logger


class NexusHub:
    """中央神经枢纽：统一缓存外部信号并按队列顺序消费。"""

    def __init__(self) -> None:
        # 核心缓冲池：所有外界刺激在此排队
        self.signal_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._is_running = False

    async def push_signal(
        self, source: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """【生产者接口】非阻塞地将消息压入队列"""
        await self.signal_queue.put(
            {"source": source, "content": content, "metadata": metadata or {}}
        )
        logger.info(
            "📥 [Nexus] 收到来自 '{}' 的信号。当前排队数: {}",
            source,
            self.signal_queue.qsize(),
        )

    async def start_heartbeat(self) -> None:
        """【消费者循环】供 main.py 挂载到后台常驻运行"""
        self._is_running = True
        logger.info("🟢 [Nexus] 核心生命循环已启动，正在监听神经信号...")

        while self._is_running:
            signal = await self.signal_queue.get()
            try:
                # TODO: 预留给大脑调用的接口
                logger.info(
                    "🧠 [Nexus -> Brain] 将 {} 的信号交由 Brain 处理...",
                    signal["source"],
                )
                await asyncio.sleep(0.1)  # 模拟大模型处理耗时
            except Exception as e:
                logger.exception("❌ [Nexus 异常] 处理信号时发生错误: {}", e)
            finally:
                self.signal_queue.task_done()

    def stop_heartbeat(self) -> None:
        """优雅停机标识"""
        self._is_running = False
        logger.info("🛑 [Nexus] 核心生命循环停止中。")


# 全局单例
nexus_hub = NexusHub()
