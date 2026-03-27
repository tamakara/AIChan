from __future__ import annotations

import argparse
import html
import json
import threading
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


@dataclass(frozen=True)
class ExternalUnreadStatus:
    """外部聊天服务未读状态。"""

    ai_unread: bool
    user_unread: bool


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
    """独立客户端 HTTP 封装，不依赖 AICHan 内部模块。"""

    def __init__(self, server_url: str, timeout_seconds: float = 5.0) -> None:
        self._server_url = normalize_server_url(server_url)
        self._timeout_seconds = timeout_seconds

    def health(self) -> bool:
        raw = self._request_json(method="GET", path="/health")
        return isinstance(raw, dict) and raw.get("ok") is True

    def get_unread_status(self) -> ExternalUnreadStatus:
        raw = self._request_json(method="GET", path="/v1/status")
        if not isinstance(raw, dict):
            raise ExternalServiceError("获取未读状态失败：返回体不是对象")

        ai_unread = raw.get("ai_unread")
        user_unread = raw.get("user_unread")
        if not isinstance(ai_unread, bool):
            raise ExternalServiceError("获取未读状态失败：ai_unread 非法")
        if not isinstance(user_unread, bool):
            raise ExternalServiceError("获取未读状态失败：user_unread 非法")

        return ExternalUnreadStatus(
            ai_unread=ai_unread,
            user_unread=user_unread,
        )

    def list_messages(self, reader: str, after_id: int = 0) -> list[ExternalMessage]:
        raw = self._request_json(
            method="GET",
            path="/v1/messages",
            query={"reader": reader, "after_id": after_id},
        )
        if not isinstance(raw, list):
            raise ExternalServiceError("拉取消息失败：返回体不是列表")

        messages: list[ExternalMessage] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ExternalServiceError("拉取消息失败：列表元素不是对象")
            raw_id = item.get("id")
            sender = item.get("sender")
            text = item.get("text")
            created_at = item.get("created_at")

            if not isinstance(raw_id, int):
                raise ExternalServiceError("拉取消息失败：id 非法")
            if not isinstance(sender, str):
                raise ExternalServiceError("拉取消息失败：sender 非法")
            if not isinstance(text, str):
                raise ExternalServiceError("拉取消息失败：text 非法")
            if not isinstance(created_at, str):
                raise ExternalServiceError("拉取消息失败：created_at 非法")

            messages.append(
                ExternalMessage(
                    message_id=raw_id,
                    sender=sender,
                    text=text,
                    created_at=created_at,
                )
            )
        return messages

    def send_message(self, sender: str, text: str) -> ExternalMessage:
        raw = self._request_json(
            method="POST",
            path="/v1/messages",
            payload={"sender": sender, "text": text},
        )
        if not isinstance(raw, dict):
            raise ExternalServiceError("发送消息失败：返回体不是对象")

        raw_id = raw.get("id")
        raw_sender = raw.get("sender")
        raw_text = raw.get("text")
        created_at = raw.get("created_at")
        if not isinstance(raw_id, int):
            raise ExternalServiceError("发送消息失败：id 非法")
        if not isinstance(raw_sender, str):
            raise ExternalServiceError("发送消息失败：sender 非法")
        if not isinstance(raw_text, str):
            raise ExternalServiceError("发送消息失败：text 非法")
        if not isinstance(created_at, str):
            raise ExternalServiceError("发送消息失败：created_at 非法")

        return ExternalMessage(
            message_id=raw_id,
            sender=raw_sender,
            text=raw_text,
            created_at=created_at,
        )

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
        self._session = PromptSession(
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
        print_formatted_text(
            "提示    : 输入消息后回车发送，/exit 退出，按 Ctrl+C 退出",
            style=self._style,
        )
        print_formatted_text(line, style=self._style)

    def prompt_server_url(self, default_url: str) -> str:
        print_formatted_text("请输入要连接的 cli_server 地址。", style=self._style)
        print_formatted_text(
            f"直接回车使用默认值：{default_url}",
            style=self._style,
        )
        while True:
            raw = self._session.prompt(
                HTML("<prompt>服务地址</prompt> > "),
                default=default_url,
                style=self._style,
            ).strip()
            try:
                return normalize_server_url(raw or default_url)
            except ValueError as exc:
                self.print_error_message(f"地址格式不合法：{exc}，请重新输入。")

    def prompt_user_text(self) -> str:
        return self._session.prompt(
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
            HTML(f"<error>AIChan</error> > {content}"),
            style=self._style,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="独立 CLI 客户端（可脱离 AICHan 运行）")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="实时同步轮询间隔秒数",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=5.0,
        help="HTTP 请求超时时间（秒）",
    )
    args = parser.parse_args()
    if args.poll_interval <= 0:
        parser.error("--poll-interval 必须大于 0")
    return args


def sync_messages_once(
    client: ExternalServiceClient,
    state: LocalMessageState,
    force_pull: bool = False,
) -> list[ExternalMessage]:
    if not force_pull:
        status = client.get_unread_status()
        if not status.user_unread:
            return []

    updates = client.list_messages(reader="user", after_id=state.last_seen_id)
    if not updates:
        return []
    return state.merge_new_messages(updates)


def start_sync_worker(
    client: ExternalServiceClient,
    state: LocalMessageState,
    ui: CLIUserInterface,
    poll_interval: float,
    stop_event: threading.Event,
) -> threading.Thread:
    def _run() -> None:
        while not stop_event.is_set():
            try:
                new_messages = sync_messages_once(client=client, state=state)
                for message in new_messages:
                    ui.print_synced_message(message)
            except ExternalServiceError as exc:
                ui.print_error_message(f"实时同步失败：{exc}")
            finally:
                stop_event.wait(poll_interval)

    worker = threading.Thread(
        target=_run,
        name="cli-client-sync",
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
        if not client.health():
            raise ExternalServiceError("健康检查返回异常状态")
    except ExternalServiceError as exc:
        ui.print_error_message(f"无法连接外部聊天服务：{exc}")
        return

    ui.print_intro(server_url=server_url)
    state = LocalMessageState()
    stop_event = threading.Event()
    sync_worker: threading.Thread | None = None

    try:
        try:
            initial_messages = sync_messages_once(
                client=client,
                state=state,
                force_pull=True,
            )
        except ExternalServiceError as exc:
            ui.print_error_message(f"启动同步失败：{exc}")
            initial_messages = []
        for message in initial_messages:
            ui.print_synced_message(message)

        with patch_stdout():
            sync_worker = start_sync_worker(
                client=client,
                state=state,
                ui=ui,
                poll_interval=args.poll_interval,
                stop_event=stop_event,
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
        if sync_worker is not None and sync_worker.is_alive():
            sync_worker.join(timeout=2.0)


if __name__ == "__main__":
    run_cli_client()
