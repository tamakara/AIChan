from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ..logger import elapsed_ms, get_logger, log_info, log_warning, start_timer
from .connection_state import NapcatConnectionState

OnEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class SessionAccessRule:
    session_id: str
    enabled: bool
    require_mention: bool
    blocked_user_ids: frozenset[int]


class NapcatWsGateway:
    """NapCat 反向 WebSocket 处理器 — 事件分发 + 动作发送。"""

    def __init__(
        self,
        connection_state: NapcatConnectionState,
        action_timeout_seconds: float,
        session_whitelist: tuple[SessionAccessRule, ...],
        on_event: OnEventCallback | None = None,
    ) -> None:
        self._logger = get_logger("napcat_ws")
        self._connection_state = connection_state
        self._action_timeout_seconds = action_timeout_seconds
        self._session_rules = {rule.session_id: rule for rule in session_whitelist if rule.enabled}
        self._on_event = on_event
        self._pending_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._pending_lock = asyncio.Lock()

    def set_on_event(self, on_event: OnEventCallback) -> None:
        self._on_event = on_event

    async def handle_connection(self, websocket: WebSocket) -> None:
        self._connection_state.set(websocket)
        await websocket.accept()
        log_info(self._logger, "hub.ws_connected")

        try:
            while True:
                message = await websocket.receive_json()
                if not isinstance(message, dict):
                    continue

                if _is_event(message):
                    await self._handle_event(message)
                    continue

                if _is_action_response(message):
                    await self._resolve_action(message)
                    continue
        except WebSocketDisconnect:
            return
        finally:
            self._connection_state.clear(websocket)
            log_info(self._logger, "hub.ws_disconnected")

    # ------------------------------------------------------------------
    # 动作发送
    # ------------------------------------------------------------------

    async def send_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """通过 WS 发送 OneBot 动作并等待 echo 响应。"""
        websocket = self._connection_state.get()
        if websocket is None:
            raise RuntimeError("napcat ws not connected")

        started_at = start_timer()
        echo = str(uuid.uuid4())
        request = {
            "action": action,
            "params": params,
            "echo": echo,
        }

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

        async with self._pending_lock:
            self._pending_actions[echo] = future

        try:
            await websocket.send_json(request)
            result = await asyncio.wait_for(future, timeout=self._action_timeout_seconds)
            log_info(
                self._logger,
                "hub.ws_action_completed",
                action_type=action,
                status=result.get("status", "unknown"),
                elapsed_ms=elapsed_ms(started_at),
            )
            return result
        except TimeoutError:
            log_warning(
                self._logger,
                "hub.ws_action_timeout",
                action_type=action,
                elapsed_ms=elapsed_ms(started_at),
            )
            raise
        finally:
            async with self._pending_lock:
                self._pending_actions.pop(echo, None)

    # ------------------------------------------------------------------
    # 事件处理
    # ------------------------------------------------------------------

    async def _handle_event(self, raw_event: dict[str, Any]) -> None:
        """校验 OneBot 事件并提交到会话注册中心。"""
        if raw_event.get("post_type") != "message":
            return

        message_type = raw_event.get("message_type")
        if message_type not in {"private", "group"}:
            return

        user_id = _to_int(raw_event.get("user_id"))
        self_id = _to_int(raw_event.get("self_id"))
        if user_id is None or self_id is None or user_id == self_id:
            return

        if not _is_valid_event_time(raw_event.get("time")):
            return

        try:
            session_id = get_session_key(raw_event)
        except ValueError:
            return

        rule = self._session_rules.get(session_id)
        if rule is None or user_id in rule.blocked_user_ids:
            return

        if message_type == "group" and rule.require_mention and not is_at_bot(raw_event):
            return

        if self._on_event is not None:
            await self._on_event(raw_event)

    # ------------------------------------------------------------------
    # 动作响应解析
    # ------------------------------------------------------------------

    async def _resolve_action(self, response: dict[str, Any]) -> None:
        echo = str(response.get("echo", ""))
        if not echo:
            return

        async with self._pending_lock:
            future = self._pending_actions.get(echo)

        if future is not None and not future.done():
            future.set_result(response)


# ------------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------------

def _is_event(message: dict[str, Any]) -> bool:
    return "post_type" in message


def _is_action_response(message: dict[str, Any]) -> bool:
    return "echo" in message and "status" in message and "retcode" in message


def _is_valid_event_time(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value.is_integer()
    if isinstance(value, str):
        return value.strip().isdigit()
    return False


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def is_at_bot(event: dict[str, Any]) -> bool:
    self_id = _to_int(event.get("self_id"))
    if self_id is None:
        return False
    for segment in _message_segments(event.get("message")):
        if segment.get("type") != "at":
            continue
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        if _to_int(data.get("qq")) == self_id:
            return True
    return False


def get_session_key(event: dict[str, Any]) -> str:
    """把 OneBot 会话窗口归一成全链路唯一 session_id。"""
    message_type = event.get("message_type")
    if message_type == "private":
        user_id = _to_int(event.get("user_id"))
        if user_id is None:
            raise ValueError("private event missing user_id")
        return f"private_{user_id}"
    if message_type == "group":
        group_id = _to_int(event.get("group_id"))
        if group_id is None:
            raise ValueError("group event missing group_id")
        return f"group_{group_id}"
    raise ValueError(f"unsupported message_type: {event.get('message_type', '')}")


def get_session_metadata(event: dict[str, Any]) -> dict[str, Any]:
    session_id = get_session_key(event)
    message_type = event.get("message_type")
    metadata: dict[str, Any] = {
        "platform": "qq",
        "session_id": session_id,
        "session_type": message_type,
        "self_id": event["self_id"],
    }
    if message_type == "private":
        metadata["user_id"] = event["user_id"]
    if message_type == "group":
        metadata["group_id"] = event["group_id"]
    return metadata


def _message_segments(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
