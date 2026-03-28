from __future__ import annotations

import json
import threading
from urllib import error, parse, request

from core.entities import AgentSignal
from core.logger import logger
from hub.signal_hub import SignalHub


class CLIMessageSSEListener:
    """通过 SSE 订阅 CLI 通道新消息并转发为 AgentSignal。"""

    def __init__(
        self,
        channel_name: str,
        signal_hub: SignalHub,
        server_base_url: str,
        reconnect_delay_seconds: float = 1.0,
        socket_timeout_seconds: float = 30.0,
    ) -> None:
        if not channel_name:
            raise ValueError("channel_name 不能为空")
        if not isinstance(signal_hub, SignalHub):
            raise TypeError("signal_hub 必须是 SignalHub")
        if not server_base_url:
            raise ValueError("server_base_url 不能为空")
        if reconnect_delay_seconds <= 0:
            raise ValueError("reconnect_delay_seconds 必须大于 0")
        if socket_timeout_seconds <= 0:
            raise ValueError("socket_timeout_seconds 必须大于 0")

        self._channel_name = channel_name
        self._signal_hub = signal_hub
        self._server_base_url = server_base_url.rstrip("/")
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._socket_timeout_seconds = socket_timeout_seconds
        self._last_message_id = 0

        self._worker: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._active_response = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._worker and self._worker.is_alive():
                logger.warning("CLI SSE 监听线程已在运行，忽略重复启动")
                return

            stop_event = threading.Event()
            worker = threading.Thread(
                target=self._listen_loop,
                args=(stop_event,),
                name="cli-sse-listener",
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
            active_response = self._active_response

        # 主动关闭当前 SSE 连接，避免 read 阻塞导致 join 超时。
        if active_response is not None:
            try:
                active_response.close()
            except Exception:
                pass

        if worker.is_alive():
            worker.join(timeout=3.0)

        with self._lock:
            if self._worker is not worker:
                return
            if worker.is_alive():
                logger.warning("CLI SSE 监听线程停止超时，线程仍在退出中")
                return
            self._worker = None
            self._stop_event = None

    def _events_url(self) -> str:
        query = parse.urlencode({"reader": "ai", "after_id": self._last_message_id})
        return f"{self._server_base_url}/v1/events?{query}"

    def _listen_loop(self, stop_event: threading.Event) -> None:
        try:
            while not stop_event.is_set():
                try:
                    url = self._events_url()
                    logger.info(
                        "📡 [CLISSE] 建立 SSE 连接，channel='{}'，after_id={}",
                        self._channel_name,
                        self._last_message_id,
                    )
                    req = request.Request(
                        url=url,
                        headers={"Accept": "text/event-stream"},
                        method="GET",
                    )
                    with request.urlopen(req, timeout=self._socket_timeout_seconds) as resp:
                        with self._lock:
                            self._active_response = resp
                        try:
                            self._consume_stream(resp, stop_event)
                        finally:
                            with self._lock:
                                if self._active_response is resp:
                                    self._active_response = None
                except error.URLError as exc:
                    if stop_event.is_set():
                        break
                    logger.warning("CLISSE 网络错误：{}，将在短暂等待后重连", exc)
                except Exception as exc:
                    if stop_event.is_set():
                        break
                    logger.error(
                        "CLISSE 监听异常：{}: {}，将在短暂等待后重连",
                        exc.__class__.__name__,
                        exc,
                    )
                finally:
                    stop_event.wait(self._reconnect_delay_seconds)
        finally:
            with self._lock:
                if self._stop_event is stop_event:
                    self._worker = None
                    self._stop_event = None

    def _consume_stream(
        self,
        response,
        stop_event: threading.Event,
    ) -> None:
        event_id: str | None = None
        event_name = "message"
        data_lines: list[str] = []

        for raw_line in response:
            if stop_event.is_set():
                return

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":
                self._handle_event(event_id=event_id, event_name=event_name, data_lines=data_lines)
                event_id = None
                event_name = "message"
                data_lines = []
                continue

            if line.startswith(":"):
                # keep-alive comment
                continue

            field, sep, value = line.partition(":")
            if not sep:
                continue
            if value.startswith(" "):
                value = value[1:]

            if field == "id":
                event_id = value
            elif field == "event":
                event_name = value
            elif field == "data":
                data_lines.append(value)

        # 连接断开前可能有未提交事件，尝试处理一次。
        self._handle_event(event_id=event_id, event_name=event_name, data_lines=data_lines)

    def _handle_event(
        self,
        event_id: str | None,
        event_name: str,
        data_lines: list[str],
    ) -> None:
        if event_name != "message" or not data_lines:
            return

        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            logger.warning("CLISSE 收到无法解析的 JSON 事件，已忽略")
            return

        if not isinstance(payload, dict):
            logger.warning("CLISSE 收到非法事件载荷（非对象），已忽略")
            return

        raw_id = payload.get("id", event_id)
        sender = payload.get("sender")
        try:
            message_id = int(raw_id)
        except (TypeError, ValueError):
            logger.warning("CLISSE 收到非法 message id，已忽略")
            return

        if message_id <= self._last_message_id:
            return
        self._last_message_id = message_id

        if sender != "user":
            return

        self._signal_hub.push_signal(AgentSignal(channel=self._channel_name))
        logger.info(
            "🔔 [CLISSE] 收到新 user 消息事件，message_id={}，已推送 AgentSignal",
            message_id,
        )
