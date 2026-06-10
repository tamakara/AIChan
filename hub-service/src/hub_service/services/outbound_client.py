from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol

import httpx

from ..logger import elapsed_ms, get_logger, log_info, start_timer
from ..router.schemas import (
    SessionCreateRequest,
    SessionCreateResponse,
    SessionChatRequest,
    SessionChatResponse,
)
from .message_xml import ReplyFileUpload, ReplyOnebotMessage, reply_xml_to_outbound_items
from .napcat_ws import NapcatWsGateway


class ReplyMediaStorageProtocol(Protocol):
    async def metadata(self, object_key: str) -> Any:
        ...

    async def content(self, object_key: str) -> bytes:
        ...


@dataclass(frozen=True)
class AgentReply:
    output_xml: str


class OutboundClient:
    """下游通信客户端 — agent-service HTTP + NapCat WS 动作发送。"""

    def __init__(
        self,
        agent_service_url: str,
        napcat_ws: NapcatWsGateway,
        media_storage: ReplyMediaStorageProtocol | None = None,
    ) -> None:
        self._logger = get_logger("outbound_client")
        self._agent_service_url = agent_service_url.rstrip("/")
        self._napcat_ws = napcat_ws
        self._media_storage = media_storage
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

    async def queue_session_message(self, agent_session_id: str, input_xml: str) -> None:
        """向正在运行的 agent 会话追加用户消息。忽略下游短暂失败。"""
        try:
            await self._post_json(
                f"{self._agent_service_url}/sessions/{agent_session_id}/queue-message",
                {"input_xml": input_xml},
            )
        except RuntimeError:
            pass

    async def call_session(
        self,
        hub_session_key: str,
        agent_session_id: str,
        input_xml: str,
    ) -> AgentReply:
        """向 agent-service 发送消息，返回已解析的 XML 回复。"""
        started_at = start_timer()
        payload = SessionChatRequest(
            session_id=agent_session_id,
            input_xml=input_xml,
        )
        data = await self._post_json(f"{self._agent_service_url}/chat", payload.model_dump())
        response = SessionChatResponse.model_validate(data)
        log_info(
            self._logger,
            "hub.downstream_called",
            session_key=hub_session_key,
            status="ok",
            elapsed_ms=elapsed_ms(started_at),
        )
        return AgentReply(output_xml=response.output_xml)

    async def send_reply(
        self,
        session_key: str,
        output_xml: str,
    ) -> None:
        """将 agent-service 返回的 AICHAN XML 回复转为 OneBot v11 私聊动作。"""
        started_at = start_timer()
        items = await reply_xml_to_outbound_items(output_xml, media_storage=self._media_storage)
        if not items:
            return

        if not session_key.startswith("private:"):
            raise ValueError(f"invalid session_key: {session_key}")

        user_id = int(session_key.split(":", 1)[1])
        for item in items:
            if isinstance(item, ReplyOnebotMessage):
                await self._napcat_ws.send_action(
                    action="send_private_msg",
                    params={"user_id": user_id, "message": item.message, "auto_escape": False},
                )
                continue

            if isinstance(item, ReplyFileUpload):
                await self._napcat_ws.send_action(
                    action="upload_private_file",
                    params={"user_id": user_id, "file": item.file, "name": item.name},
                )
        log_info(
            self._logger,
            "hub.reply_sent",
            session_key=session_key,
            reply_len=len(output_xml),
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
