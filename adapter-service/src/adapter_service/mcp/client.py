from __future__ import annotations

import json
from typing import Any

import httpx


class AdapterClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def get_message_history(
        self,
        session_id: str,
        limit: int,
        before_message_id: int | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"session_id": session_id, "limit": limit}
        if before_message_id is not None:
            params["before_message_id"] = before_message_id

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                response = await client.get("/api/v1/message/history", params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                # 这里显式附带 adapter 错误体，便于 agent 判断是参数错误还是下游可重试故障。
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"adapter-service history request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"adapter-service request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("adapter-service returned non-json payload") from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"adapter-service returned invalid payload: {payload}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("adapter-service returned invalid history payload")

        return data


def _try_extract_error_detail(response: httpx.Response) -> str:
    # 统一序列化错误详情，确保 MCP 返回文本在 agent 侧可直接记录与诊断。
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)

