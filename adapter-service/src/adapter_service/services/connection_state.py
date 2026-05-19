from __future__ import annotations

from fastapi import WebSocket


class NapcatConnectionState:
    def __init__(self) -> None:
        self._websocket: WebSocket | None = None

    def set(self, websocket: WebSocket) -> None:
        self._websocket = websocket

    def clear(self, websocket: WebSocket) -> None:
        if self._websocket is websocket:
            self._websocket = None

    def get(self) -> WebSocket | None:
        return self._websocket
