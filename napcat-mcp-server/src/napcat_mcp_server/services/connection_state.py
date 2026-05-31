from __future__ import annotations

from fastapi import WebSocket


class NapcatConnectionState:
    """当前活跃的 NapCat 反向 WS 连接引用（单例）。"""

    def __init__(self) -> None:
        self._websocket: WebSocket | None = None

    def set(self, websocket: WebSocket) -> None:
        self._websocket = websocket

    def clear(self, websocket: WebSocket) -> None:
        if self._websocket is websocket:
            self._websocket = None

    def get(self) -> WebSocket | None:
        return self._websocket
