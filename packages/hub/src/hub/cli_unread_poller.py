from __future__ import annotations

import threading

from core.entities import AgentSignal
from core.logger import logger
from hub.signal_hub import SignalHub
from plugins.channels.cli import CLIChannelPlugin


class CLIUnreadPoller:
    """CLI 未读轮询线程运行时对象。"""

    def __init__(
        self,
        cli_channel: CLIChannelPlugin,
        signal_hub: SignalHub,
        interval_seconds: float,
    ):
        if not isinstance(cli_channel, CLIChannelPlugin):
            raise TypeError("cli_channel 必须是 CLIChannelPlugin")
        if not isinstance(signal_hub, SignalHub):
            raise TypeError("signal_hub 必须是 SignalHub")
        self._cli_channel = cli_channel
        self._signal_hub = signal_hub
        self._interval_seconds = self._validate_interval_seconds(interval_seconds)
        self._worker: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._lock = threading.Lock()

    @staticmethod
    def _validate_interval_seconds(value: float) -> float:
        if value <= 0:
            raise ValueError("interval_seconds 必须大于 0")
        return value

    @property
    def interval_seconds(self) -> float:
        return self._interval_seconds

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                logger.warning("CLI 未读轮询线程已在运行，忽略重复启动")
                return

            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._poll_loop,
                args=(self._cli_channel, stop_event),
                name="cli-unread-poller",
                daemon=True,
            )
            self._stop_event = stop_event
            self._worker = worker
            worker.start()

    def stop(self) -> None:
        with self._lock:
            worker = self._worker
            stop_event = self._stop_event
            if worker is None or stop_event is None:
                return
            stop_event.set()

        if worker.is_alive():
            worker.join(timeout=3.0)

        with self._lock:
            if self._worker is not worker:
                return
            if worker.is_alive():
                logger.warning("CLI 未读轮询线程停止超时，线程仍在退出中")
                return
            self._worker = None
            self._stop_event = None

    def _poll_loop(
        self,
        cli_channel: CLIChannelPlugin,
        stop_event: threading.Event,
    ) -> None:
        try:
            while not stop_event.is_set():
                try:
                    emitted = cli_channel.emit_signal_if_ai_unread(
                        emit_signal=lambda channel_name: self._signal_hub.push_signal(
                            AgentSignal(channel=channel_name)
                        )
                    )
                    if emitted:
                        logger.info("🔔 检测到 CLI 未读，已发出 AgentSignal")
                except Exception as exc:
                    logger.error(
                        "CLI 未读轮询失败：{}: {}",
                        exc.__class__.__name__,
                        exc,
                    )
                finally:
                    stop_event.wait(self._interval_seconds)
        finally:
            with self._lock:
                if self._stop_event is stop_event:
                    self._worker = None
                    self._stop_event = None
