from __future__ import annotations

import queue
import threading
import time

from core.entities import AgentSignal
from hub.signal_processor import SignalProcessor

from core.logger import logger


class SignalHub:
    """中央神经枢纽：统一缓存外部信号并按队列顺序消费。"""

    def __init__(self, signal_processor: SignalProcessor) -> None:
        # 核心缓冲池：所有外界刺激在此排队（线程安全）。
        self.signal_queue: queue.Queue[AgentSignal] = queue.Queue()
        self._signal_processor = signal_processor
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_running = False

    def push_signal(self, signal: AgentSignal) -> None:
        """【生产者接口】将信号压入队列。"""
        if not self._is_running:
            raise RuntimeError("SignalHub 未启动，无法接收信号。")
        self.signal_queue.put(signal)
        logger.info(
            "📥 [SignalHub] 收到来自 '{}' 的信号。当前排队数: {}",
            signal.channel,
            self.signal_queue.qsize(),
        )

    def _heartbeat_loop(self) -> None:
        logger.info("🟢 [SignalHub] 核心生命循环已启动，正在监听神经信号...")
        signal_seq = 0

        while not self._stop_event.is_set():
            try:
                signal = self.signal_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                signal_seq += 1
                signal_id = f"{signal.channel}#{signal_seq}"
                started_at = time.perf_counter()
                logger.info(
                    "🧠 [SignalHub -> SignalProcessor] signal_id={} 将 {} 的信号交由处理器处理...",
                    signal_id,
                    signal.channel,
                )
                handled_count = self._signal_processor.process_signal(
                    signal=signal,
                    signal_id=signal_id,
                )
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.info(
                    "✅ [SignalHub <- SignalProcessor] signal_id={} 处理完成，user消息处理数={}，耗时={}ms",
                    signal_id,
                    handled_count,
                    elapsed_ms,
                )
            except Exception as e:
                logger.error(
                    "❌ [SignalHub 异常] 处理信号时发生错误: {}: {}",
                    e.__class__.__name__,
                    e,
                )
            finally:
                self.signal_queue.task_done()

        self._is_running = False
        logger.info("🛑 [SignalHub] 核心生命循环已停止。")

    def start_heartbeat(self) -> None:
        """【消费者循环】挂载后台线程常驻运行。"""
        if self._is_running:
            return
        self._stop_event.clear()
        self._is_running = True
        self._worker = threading.Thread(
            target=self._heartbeat_loop,
            name="hub-heartbeat",
            daemon=True,
        )
        self._worker.start()

    def stop_heartbeat(self, wait: bool = True) -> None:
        """优雅停机标识；可选等待后台线程退出。"""
        self._stop_event.set()
        if wait and self._worker and self._worker.is_alive():
            self._worker.join(timeout=3.0)
        self._is_running = False
        logger.info("🛑 [SignalHub] 核心生命循环停止中。")
