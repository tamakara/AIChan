from __future__ import annotations

import argparse
import html
import json
import threading
import time
from dataclasses import dataclass
from urllib import error, parse, request

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style

DEFAULT_SERVER_URL = "http://127.0.0.1:8765"


class ExternalServiceError(RuntimeError):
    """外部聊天服务通信异常。"""


def normalize_server_url(raw_url: str) -> str:
    """规范化并校验服务地址。"""
    candidate = raw_url.strip().rstrip("/")
    if not candidate:
        raise ValueError("服务地址不能为空")

    # 允许输入 127.0.0.1:8765 / localhost:8765，自动补全协议。
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    parsed = parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("仅支持 http 或 https 协议")
    if not parsed.netloc:
        raise ValueError("缺少主机名或端口")
    return candidate


@dataclass(frozen=True)
class ExternalMessage:
    """外部聊天服务消息结构。"""

    message_id: int
    sender: str
    text: str
    created_at: str


class LocalMessageState:
    """客户端本地消息状态。"""

    def __init__(self) -> None:
        self._messages: list[ExternalMessage] = []
        self._known_ids: set[int] = set()
        self._last_seen_id = 0
        self._lock = threading.Lock()

    @property
    def last_seen_id(self) -> int:
        with self._lock:
            return self._last_seen_id

    def merge_new_messages(
        self,
        incoming: list[ExternalMessage],
    ) -> list[ExternalMessage]:
        new_messages: list[ExternalMessage] = []
        with self._lock:
            for message in incoming:
                if message.message_id in self._known_ids:
                    continue
                self._messages.append(message)
                self._known_ids.add(message.message_id)
                self._last_seen_id = max(self._last_seen_id, message.message_id)
                new_messages.append(message)
        return new_messages


class ExternalServiceClient:
    """独立客户端 HTTP 封装。"""

    def __init__(self, server_url: str, timeout_seconds: float = 5.0) -> None:
        self._server_url = normalize_server_url(server_url)
        self._timeout_seconds = timeout_seconds

    def health(self) -> bool:
        raw = self._request_json(method="GET", path="/health")
        return isinstance(raw, dict) and raw.get("ok") is True

    def list_messages(self, after_id: int = 0) -> list[ExternalMessage]:
        raw = self._request_json(
            method="GET",
            path="/v1/messages",
            query={"after_id": after_id},
        )
        if not isinstance(raw, list):
            raise ExternalServiceError("拉取消息失败：返回体不是列表")

        messages: list[ExternalMessage] = []
        for item in raw:
            messages.append(self.parse_external_message(item))
        return messages

    def send_message(self, sender: str, text: str) -> ExternalMessage:
        raw = self._request_json(
            method="POST",
            path="/v1/messages",
            payload={"sender": sender, "text": text},
        )
        if not isinstance(raw, dict):
            raise ExternalServiceError("发送消息失败：返回体不是对象")

        return self.parse_external_message(raw)

    def parse_external_message(self, raw: object) -> ExternalMessage:
        if not isinstance(raw, dict):
            raise ExternalServiceError("消息解析失败：返回体不是对象")

        raw_id = raw.get("id")
        raw_sender = raw.get("sender")
        raw_text = raw.get("text")
        created_at = raw.get("created_at")
        if not isinstance(raw_id, int):
            raise ExternalServiceError("消息解析失败：id 非法")
        if not isinstance(raw_sender, str):
            raise ExternalServiceError("消息解析失败：sender 非法")
        if not isinstance(raw_text, str):
            raise ExternalServiceError("消息解析失败：text 非法")
        if not isinstance(created_at, str):
            raise ExternalServiceError("消息解析失败：created_at 非法")

        return ExternalMessage(
            message_id=raw_id,
            sender=raw_sender,
            text=raw_text,
            created_at=created_at,
        )

    def build_events_url(self, after_id: int = 0) -> str:
        query = parse.urlencode({"after_id": after_id})
        return f"{self._server_url}/v1/events?{query}"

    def _request_json(
        self,
        method: str,
        path: str,
        query: dict[str, object] | None = None,
        payload: object | None = None,
    ) -> object:
        url = f"{self._server_url}{path}"
        if query:
            url = f"{url}?{parse.urlencode(query)}"

        body = None
        headers: dict[str, str] = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as resp:
                raw_text = resp.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ExternalServiceError(
                f"HTTP 请求失败（{exc.code}）：{detail or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise ExternalServiceError(f"无法连接服务：{exc.reason}") from exc

        if not raw_text:
            return {}
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ExternalServiceError("服务返回非 JSON 内容") from exc


class CLIUserInterface:
    """基于 prompt_toolkit 的终端交互层。"""

    def __init__(self) -> None:
        self._style = Style.from_dict(
            {
                "prompt": "ansicyan bold",
                "ai": "ansimagenta bold",
                "user": "ansigreen bold",
                "system": "ansiyellow bold",
                "error": "ansired bold",
            }
        )
        self._server_session = PromptSession(
            complete_while_typing=False,
            enable_history_search=True,
        )
        self._chat_session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=False,
            enable_history_search=True,
            erase_when_done=True,
        )

    def print_intro(self, server_url: str) -> None:
        line = "=" * 72
        print_formatted_text(line, style=self._style)
        print_formatted_text(
            HTML("<system>独立 CLI 客户端（prompt_toolkit）</system>"),
            style=self._style,
        )
        print_formatted_text("通信对象: user <-> ai", style=self._style)
        print_formatted_text(f"服务地址: {server_url}", style=self._style)
        print_formatted_text("消息同步: SSE (/v1/events)", style=self._style)
        print_formatted_text(
            "提示    : 输入消息后回车发送，/exit 退出，按 Ctrl+C 退出",
            style=self._style,
        )
        print_formatted_text(line, style=self._style)

    def prompt_server_url(self, default_url: str) -> str:
        print_formatted_text("请输入要连接的 cli_gateway 地址。", style=self._style)
        print_formatted_text(
            f"直接回车使用默认值：{default_url}",
            style=self._style,
        )
        while True:
            raw = self._server_session.prompt(
                HTML("<prompt>服务地址</prompt> > "),
                default=default_url,
                style=self._style,
            ).strip()
            try:
                return normalize_server_url(raw or default_url)
            except ValueError as exc:
                self.print_error_message(f"地址格式不合法：{exc}，请重新输入。")

    def prompt_user_text(self) -> str:
        return self._chat_session.prompt(
            HTML("<prompt>user</prompt> > "),
            style=self._style,
        )

    def print_synced_message(self, message: ExternalMessage) -> None:
        speaker = "user" if message.sender == "user" else "ai"

        content = message.text.strip() or "（空消息）"
        lines = content.splitlines()
        first_line = html.escape(lines[0])
        print_formatted_text(
            HTML(f"<{speaker}>{speaker}</{speaker}> > {first_line}"),
            style=self._style,
        )
        for line in lines[1:]:
            print_formatted_text(f"  {line}", style=self._style)

    def print_system_message(self, text: str) -> None:
        content = html.escape(text)
        print_formatted_text(
            HTML(f"<system>system</system> > {content}"),
            style=self._style,
        )

    def print_error_message(self, text: str) -> None:
        content = html.escape(text)
        print_formatted_text(
            HTML(f"<error>error</error> > {content}"),
            style=self._style,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立 CLI 客户端")
    parser.add_argument(
        "--connect-retry-delay",
        type=float,
        default=3.0,
        help="服务不可达时重试连接间隔（秒）",
    )
    parser.add_argument(
        "--sse-reconnect-delay",
        type=float,
        default=1.0,
        help="SSE 断线后重连等待秒数",
    )
    parser.add_argument(
        "--sse-timeout",
        type=float,
        default=30.0,
        help="SSE 连接 socket 超时时间（秒）",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=5.0,
        help="HTTP 请求超时时间（秒）",
    )
    args = parser.parse_args()
    if args.connect_retry_delay <= 0:
        parser.error("--connect-retry-delay 必须大于 0")
    if args.sse_reconnect_delay <= 0:
        parser.error("--sse-reconnect-delay 必须大于 0")
    if args.sse_timeout <= 0:
        parser.error("--sse-timeout 必须大于 0")
    if args.http_timeout <= 0:
        parser.error("--http-timeout 必须大于 0")
    return args


def wait_for_service_online(
    client: ExternalServiceClient,
    ui: CLIUserInterface,
    retry_delay_seconds: float,
) -> None:
    """阻塞等待外部服务可用，失败后按固定间隔持续重试。"""
    while True:
        try:
            if client.health():
                ui.print_system_message("外部聊天服务连接成功。")
                return
            ui.print_error_message("健康检查返回异常状态。")
        except ExternalServiceError as exc:
            ui.print_error_message(f"无法连接外部聊天服务：{exc}")

        ui.print_system_message(
            f"{retry_delay_seconds:g} 秒后重试连接（Ctrl+C 取消）。"
        )
        time.sleep(retry_delay_seconds)


def load_initial_messages_with_retry(
    client: ExternalServiceClient,
    state: LocalMessageState,
    ui: CLIUserInterface,
    retry_delay_seconds: float,
) -> list[ExternalMessage]:
    """启动阶段拉取历史消息，失败后按固定间隔持续重试。"""
    while True:
        try:
            initial_messages = client.list_messages(after_id=state.last_seen_id)
            return state.merge_new_messages(initial_messages)
        except ExternalServiceError as exc:
            ui.print_error_message(f"启动同步失败：{exc}")
            ui.print_system_message(
                f"{retry_delay_seconds:g} 秒后重试拉取历史消息（Ctrl+C 取消）。"
            )
            time.sleep(retry_delay_seconds)


def start_sse_sync_worker(
    client: ExternalServiceClient,
    state: LocalMessageState,
    ui: CLIUserInterface,
    stop_event: threading.Event,
    reconnect_delay_seconds: float,
    sse_timeout_seconds: float,
) -> threading.Thread:
    def _handle_sse_event(
        event_id: str | None,
        event_name: str,
        data_lines: list[str],
    ) -> int | None:
        _ = event_id
        if event_name != "message" or not data_lines:
            return None

        raw_data = "\n".join(data_lines).strip()
        if not raw_data:
            return None

        try:
            payload = json.loads(raw_data)
            message = client.parse_external_message(payload)
        except (json.JSONDecodeError, ExternalServiceError):
            ui.print_error_message("实时同步失败：收到非法 SSE 消息事件")
            return None

        new_messages = state.merge_new_messages([message])
        for item in new_messages:
            ui.print_synced_message(item)

        return message.message_id

    def _run() -> None:
        last_id = state.last_seen_id
        while not stop_event.is_set():
            try:
                url = client.build_events_url(after_id=last_id)
                req = request.Request(
                    url=url,
                    headers={"Accept": "text/event-stream"},
                    method="GET",
                )
                with request.urlopen(req, timeout=sse_timeout_seconds) as resp:
                    event_id: str | None = None
                    event_name = "message"
                    data_lines: list[str] = []
                    for raw_line in resp:
                        if stop_event.is_set():
                            return

                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if line == "":
                            handled_id = _handle_sse_event(
                                event_id=event_id,
                                event_name=event_name,
                                data_lines=data_lines,
                            )
                            if handled_id is not None:
                                last_id = max(last_id, handled_id)
                            event_id = None
                            event_name = "message"
                            data_lines = []
                            continue

                        if line.startswith(":"):
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

                    handled_id = _handle_sse_event(
                        event_id=event_id,
                        event_name=event_name,
                        data_lines=data_lines,
                    )
                    if handled_id is not None:
                        last_id = max(last_id, handled_id)
            except (ExternalServiceError, error.URLError, TimeoutError) as exc:
                ui.print_error_message(
                    f"实时同步失败：{exc}，{reconnect_delay_seconds:g} 秒后重连"
                )
            finally:
                stop_event.wait(reconnect_delay_seconds)

    worker = threading.Thread(
        target=_run,
        name="cli-client-sse-sync",
        daemon=True,
    )
    worker.start()
    return worker


def run_cli_client() -> None:
    args = parse_args()
    ui = CLIUserInterface()

    try:
        server_url = ui.prompt_server_url(default_url=DEFAULT_SERVER_URL)
    except (KeyboardInterrupt, EOFError):
        print("\n已取消连接。")
        return

    client = ExternalServiceClient(
        server_url=server_url,
        timeout_seconds=args.http_timeout,
    )

    try:
        wait_for_service_online(
            client=client,
            ui=ui,
            retry_delay_seconds=args.connect_retry_delay,
        )
    except KeyboardInterrupt:
        ui.print_system_message("已取消连接。")
        return

    ui.print_intro(server_url=server_url)
    state = LocalMessageState()
    stop_event = threading.Event()
    sse_worker: threading.Thread | None = None

    try:
        try:
            initial_messages = load_initial_messages_with_retry(
                client=client,
                state=state,
                ui=ui,
                retry_delay_seconds=args.connect_retry_delay,
            )
        except KeyboardInterrupt:
            ui.print_system_message("已取消同步，CLI 客户端退出。")
            return
        for message in initial_messages:
            ui.print_synced_message(message)

        with patch_stdout():
            sse_worker = start_sse_sync_worker(
                client=client,
                state=state,
                ui=ui,
                stop_event=stop_event,
                reconnect_delay_seconds=args.sse_reconnect_delay,
                sse_timeout_seconds=args.sse_timeout,
            )
            while True:
                try:
                    text = ui.prompt_user_text().strip()
                except KeyboardInterrupt:
                    ui.print_system_message("CLI 客户端已退出。")
                    break
                except EOFError:
                    ui.print_system_message("输入流结束，CLI 客户端已退出。")
                    break

                if not text:
                    ui.print_system_message("请输入内容后再发送。")
                    continue
                if text in {"/exit", "/quit"}:
                    ui.print_system_message("CLI 客户端已退出。")
                    break

                try:
                    client.send_message(sender="user", text=text)
                except ExternalServiceError as exc:
                    ui.print_error_message(f"发送失败：{exc}")
    finally:
        stop_event.set()
        if sse_worker is not None and sse_worker.is_alive():
            sse_worker.join(timeout=2.0)


if __name__ == "__main__":
    run_cli_client()

