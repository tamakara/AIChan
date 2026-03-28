from __future__ import annotations

from typing import cast

from core.http_client import HTTPClient, HTTPClientError
from plugins.channels.cli.models import (
    CLIChannelMessage,
    CLIChannelReader,
    CLIChannelSender,
)


class CLIMessageServiceError(RuntimeError):
    """CLI 外部消息服务访问异常。"""


class CLIMessageServiceClient:
    """CLI 外部消息服务 HTTP 客户端。"""

    def __init__(
        self,
        server_base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._http = HTTPClient(
            base_url=server_base_url,
            timeout_seconds=timeout_seconds,
        )

    def health(self) -> bool:
        try:
            raw = self._http.request_json(method="GET", path="/health")
        except HTTPClientError as exc:
            raise CLIMessageServiceError(f"健康检查失败：{exc}") from exc

        return isinstance(raw, dict) and raw.get("ok") is True

    def list_messages(
        self,
        reader: CLIChannelReader,
        after_id: int = 0,
    ) -> list[CLIChannelMessage]:
        try:
            raw = self._http.request_json(
                method="GET",
                path="/v1/messages",
                query={"reader": reader, "after_id": after_id},
            )
        except HTTPClientError as exc:
            raise CLIMessageServiceError(f"拉取消息失败：{exc}") from exc

        if not isinstance(raw, list):
            raise CLIMessageServiceError("拉取消息失败：返回体不是列表")

        return [self._parse_external_message(item) for item in raw]

    def send_message(
        self,
        sender: CLIChannelSender,
        text: str,
    ) -> CLIChannelMessage:
        try:
            raw = self._http.request_json(
                method="POST",
                path="/v1/messages",
                payload={"sender": sender, "text": text},
            )
        except HTTPClientError as exc:
            raise CLIMessageServiceError(f"发送消息失败：{exc}") from exc

        return self._parse_external_message(raw)

    def _parse_external_message(self, raw: object) -> CLIChannelMessage:
        if not isinstance(raw, dict):
            raise CLIMessageServiceError("消息解析失败：返回项不是对象")

        raw_id = raw.get("id")
        sender = raw.get("sender")
        text = raw.get("text")
        created_at = raw.get("created_at")

        if not isinstance(raw_id, int) or raw_id < 1:
            raise CLIMessageServiceError("消息解析失败：id 非法")
        if sender not in {"ai", "user"}:
            raise CLIMessageServiceError("消息解析失败：sender 非法")
        if not isinstance(text, str):
            raise CLIMessageServiceError("消息解析失败：text 非法")
        if not isinstance(created_at, str) or not created_at:
            raise CLIMessageServiceError("消息解析失败：created_at 非法")

        normalized_sender = cast(CLIChannelSender, sender)
        return CLIChannelMessage(
            message_id=raw_id,
            sender=normalized_sender,
            text=text,
            created_at=created_at,
        )
