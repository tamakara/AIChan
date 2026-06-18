from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from ..logger import elapsed_ms, get_logger, log_exception, log_info, start_timer
from .memory_client import MemoryClient
from .session import MemoryCompressionSnapshot, Session


class MemoryCompressionScheduler(Protocol):
    def schedule(self, session: Session, snapshot: MemoryCompressionSnapshot) -> bool:
        pass

    def shutdown(self, timeout_seconds: float) -> None:
        pass


class NoopMemoryCompressionScheduler:
    def schedule(self, session: Session, snapshot: MemoryCompressionSnapshot) -> bool:
        return False

    def shutdown(self, timeout_seconds: float) -> None:
        return


class ThreadedMemoryCompressionScheduler:
    def __init__(self, memory_client: MemoryClient, *, max_workers: int = 1) -> None:
        self._logger = get_logger("memory_compression")
        self._memory_client = memory_client
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="memory-compress",
        )
        self._lock = Lock()
        self._futures: set[Future[None]] = set()

    def schedule(self, session: Session, snapshot: MemoryCompressionSnapshot) -> bool:
        future = self._executor.submit(self._run_job, session, snapshot)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)
        return True

    def shutdown(self, timeout_seconds: float) -> None:
        # 压缩是附加收益，不值得在关停时无限等待；这里直接停止接单，
        # 已在执行的任务让解释器退出时自然收口即可。
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _discard_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def _run_job(self, session: Session, snapshot: MemoryCompressionSnapshot) -> None:
        started_at = start_timer()
        try:
            result = self._memory_client.compress(session.session_id, snapshot.messages_text)
        except Exception:
            with session._lock:
                session.fail_memory_compression_locked(target_max_seq=snapshot.target_max_seq)
            log_exception(
                self._logger,
                "agent.memory_compress_failed",
                session_id=session.session_id,
                elapsed_ms=elapsed_ms(started_at),
            )
            return

        with session._lock:
            session.complete_memory_compression_locked(
                target_max_seq=snapshot.target_max_seq,
                memory_markdown=result.content_markdown,
            )
        log_info(
            self._logger,
            "agent.memory_compress_completed",
            session_id=session.session_id,
            elapsed_ms=elapsed_ms(started_at),
        )
