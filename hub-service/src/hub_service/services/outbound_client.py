from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ..logger import elapsed_ms, get_logger, log_info, start_timer
from ..router.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionChatRequest,
    SessionChatResponse,
)
from .napcat_ws import NapcatWsGateway


@dataclass(frozen=True)
class AgentReply:
    content: str | list[dict[str, Any]]
    auto_escape: bool


class OutboundClient:
    """下游通信客户端 — agent-service HTTP + NapCat WS 动作发送。"""

    def __init__(
        self,
        agent_service_url: str,
        napcat_ws: NapcatWsGateway,
    ) -> None:
        self._logger = get_logger("outbound_client")
        self._agent_service_url = agent_service_url.rstrip("/")
        self._napcat_ws = napcat_ws
        self._client = httpx.AsyncClient(timeout=None)

    async def create_session(self, hub_session_key: str, metadata: dict[str, Any]) -> str:
        """在 agent-service 中创建会话，返回 agent 侧的 session_id。"""
        started_at = start_timer()
        payload = SessionCreateRequest(metadata=metadata)
        data = await self._post_json(f"{self._agent_service_url}/sessions", payload.model_dump())
        response = SessionCreateResponse.model_validate(data)
        log_info(
            self._logger,
            "hub.downstream_called",
            session_key=hub_session_key,
            status="ok",
            elapsed_ms=elapsed_ms(started_at),
        )
        return response.session_id

    async def interrupt_session(self, agent_session_id: str) -> None:
        """中断 agent-service 中正在运行的会话。忽略 404 等异常。"""
        try:
            await self._post_json(
                f"{self._agent_service_url}/sessions/{agent_session_id}/interrupt",
                {},
            )
        except RuntimeError:
            pass  # session 不存在或未被中断，不影响主流程

    async def call_session(
        self,
        hub_session_key: str,
        agent_session_id: str,
        text: str,
    ) -> AgentReply | None:
        """向 agent-service 发送消息，返回已解析的回复。被中断返回 None。"""
        started_at = start_timer()
        payload = SessionChatRequest(
            session_id=agent_session_id,
            batch=text,
        )
        try:
            data = await self._post_json(f"{self._agent_service_url}/chat", payload.model_dump())
        except RuntimeError as exc:
            if "status=409" in str(exc):
                log_info(
                    self._logger,
                    "hub.downstream_interrupted",
                    session_key=hub_session_key,
                    elapsed_ms=elapsed_ms(started_at),
                )
                return None
            raise
        response = SessionChatResponse.model_validate(data)
        log_info(
            self._logger,
            "hub.downstream_called",
            session_key=hub_session_key,
            status="ok",
            elapsed_ms=elapsed_ms(started_at),
        )
        return AgentReply(content=response.reply, auto_escape=response.auto_escape)

    async def send_reply(
        self,
        session_key: str,
        content: str | list[dict[str, Any]],
        auto_escape: bool,
    ) -> None:
        """将 agent-service 返回的回复转为 OneBot v11 动作并发送。"""
        started_at = start_timer()

        message = _message_to_wire(content)

        if session_key.startswith("group:"):
            group_id = int(session_key.split(":", 1)[1])
            action = "send_group_msg"
            params = {"group_id": group_id, "message": message, "auto_escape": auto_escape}
        elif session_key.startswith("private:"):
            user_id = int(session_key.split(":", 1)[1])
            action = "send_private_msg"
            params = {"user_id": user_id, "message": message, "auto_escape": auto_escape}
        else:
            raise ValueError(f"invalid session_key: {session_key}")

        await self._napcat_ws.send_action(action=action, params=params)
        log_info(
            self._logger,
            "hub.reply_sent",
            session_key=session_key,
            reply_len=len(str(content)),
            elapsed_ms=elapsed_ms(started_at),
        )

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(url, json=payload)
        if response.status_code >= 400:
            raise RuntimeError(
                f"downstream http error: url={url} status={response.status_code} body={response.text}"
            )
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"downstream json is not object: url={url}")

        return data

    async def aclose(self) -> None:
        await self._client.aclose()


def _message_to_wire(content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 reply 内容转为 OneBot v11 消息段数组（JSON 可序列化）。"""
    if isinstance(content, str):
        msg = Message(content)
    elif isinstance(content, list):
        segments = [
            MessageSegment(type=seg["type"], data=seg["data"])
            for seg in content
        ]
        msg = Message(segments)
    else:
        msg = Message(str(content))
    return [{"type": seg.type, "data": seg.data} for seg in msg]
