from __future__ import annotations

from typing import Any

import httpx

from ..logger import elapsed_ms, get_logger, log_info, start_timer
from ..router.schemas import (
    AgentChatRequest,
    AgentChatResponse,
    AgentInboundMessage,
    AgentRunCreateRequest,
    AgentRunCreateResponse,
)
from .redis_stream import HubRedisStream


class OutboundClient:
    def __init__(
        self,
        agent_service_url: str,
        redis_stream: HubRedisStream,
    ) -> None:
        self._logger = get_logger("outbound_client")
        self._agent_service_url = agent_service_url.rstrip("/")
        self._redis_stream = redis_stream
        self._client = httpx.AsyncClient(timeout=None)

    async def create_agent_run(self, session_id: str, metadata: dict[str, Any]) -> str:
        started_at = start_timer()
        payload = AgentRunCreateRequest(metadata=metadata)
        data = await self._post_json(f"{self._agent_service_url}/agent-runs", payload.model_dump())
        response = AgentRunCreateResponse.model_validate(data)
        log_info(
            self._logger,
            "hub.downstream_called",
            session_id=session_id,
            status="ok",
            elapsed_ms=elapsed_ms(started_at),
        )
        return response.agent_id

    async def call_agent(
        self,
        session_id: str,
        agent_id: str,
        messages: list[AgentInboundMessage],
    ) -> str:
        started_at = start_timer()
        payload = AgentChatRequest(
            agent_id=agent_id,
            messages=messages,
        )
        data = await self._post_json(f"{self._agent_service_url}/chat", payload.model_dump())
        response = AgentChatResponse.model_validate(data)
        log_info(
            self._logger,
            "hub.downstream_called",
            session_id=session_id,
            status="ok",
            elapsed_ms=elapsed_ms(started_at),
        )
        return response.reply

    async def send_reply(self, session_id: str, content: str) -> None:
        started_at = start_timer()
        await self._redis_stream.enqueue_send_message(session_id=session_id, content=content)
        log_info(
            self._logger,
            "hub.reply_enqueued",
            session_id=session_id,
            reply_len=len(content),
            elapsed_ms=elapsed_ms(started_at),
        )

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post(url, json=payload)
        if response.status_code >= 400:
            # 下游非 2xx 时保留响应体，避免只看到状态码而丢失关键错误上下文。
            raise RuntimeError(
                f"downstream http error: url={url} status={response.status_code} body={response.text}"
            )
        data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"downstream json is not object: url={url}")

        return data

    async def aclose(self) -> None:
        await self._client.aclose()
