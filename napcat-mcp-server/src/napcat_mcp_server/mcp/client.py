from __future__ import annotations

import json
from typing import Any

import httpx


class NapcatMcpClient:
    """MCP 子进程通过 HTTP 调用主服务的 API。"""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    async def get_message_history(
        self,
        message_type: str,
        peer_id: int,
        limit: int,
        before_message_id: int | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "message_type": message_type,
            "peer_id": peer_id,
            "limit": limit,
        }
        if before_message_id is not None:
            params["before_message_id"] = before_message_id

        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                response = await client.get("/api/v1/message/history", params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"napcat-mcp history request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"napcat-mcp request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("napcat-mcp returned non-json payload") from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"napcat-mcp returned invalid payload: {payload}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("napcat-mcp returned invalid history payload")

        return data

    async def get_user_info(self, user_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(f"/api/v1/user/{user_id}/info")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"napcat-mcp user info request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"napcat-mcp request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("napcat-mcp returned non-json payload") from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"napcat-mcp returned invalid payload: {payload}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("napcat-mcp returned invalid user info payload")

        return data


def _try_extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if detail is not None:
            return json.dumps(detail, ensure_ascii=False)
    return json.dumps(payload, ensure_ascii=False)
