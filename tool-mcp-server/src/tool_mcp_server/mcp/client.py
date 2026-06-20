from __future__ import annotations

import json
from typing import Any

import httpx


class ToolMcpClient:
    """MCP 工具按领域调用下游服务，QQ 与文件能力不再共享 hub 边界。"""

    def __init__(
        self,
        qq_base_url: str,
        file_base_url: str,
        memory_base_url: str,
        timeout_seconds: float,
    ) -> None:
        self._qq_base_url = qq_base_url.rstrip("/")
        self._file_base_url = file_base_url.rstrip("/")
        self._memory_base_url = memory_base_url.rstrip("/")
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

        payload = await self._get_json(
            self._qq_base_url,
            "/api/v1/message/history",
            params=params,
            action="history",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("tool-mcp returned invalid history payload")
        return data

    async def get_user_info(self, user_id: int) -> dict[str, Any]:
        payload = await self._get_json(self._qq_base_url, f"/api/v1/user/{user_id}/info", action="user info")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("tool-mcp returned invalid user info payload")
        return data

    async def get_file_metadata(self, object_key: str) -> dict[str, Any]:
        payload = await self._get_json(
            self._file_base_url,
            f"/api/v1/files/{object_key}/metadata",
            action="file metadata",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("tool-mcp returned invalid file metadata payload")
        return data

    async def read_file_text(self, object_key: str, max_chars: int) -> dict[str, Any]:
        payload = await self._get_json(
            self._file_base_url,
            f"/api/v1/files/{object_key}/text",
            params={"max_chars": max_chars},
            action="file text",
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("tool-mcp returned invalid file text payload")
        return data

    async def get_file_content(self, object_key: str) -> bytes:
        async with httpx.AsyncClient(base_url=self._file_base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(f"/api/v1/files/{object_key}/content")
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"tool-mcp file content request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"tool-mcp request failed: {exc}") from exc
        return response.content

    async def get_user_memory(
        self,
        user_id: str,
        *,
        start_line: int,
        line_count: int,
    ) -> dict[str, Any]:
        payload = await self._get_raw_json(
            self._memory_base_url,
            f"/api/v1/users/{user_id}/memory",
            params={"start_line": start_line, "line_count": line_count},
            action="user memory",
        )
        if (
            not isinstance(payload.get("user_id"), str)
            or not isinstance(payload.get("content_markdown"), str)
            or not isinstance(payload.get("start_line"), int)
            or not isinstance(payload.get("line_count"), int)
            or not isinstance(payload.get("total_lines"), int)
            or not isinstance(payload.get("has_more"), bool)
        ):
            raise RuntimeError("tool-mcp returned invalid user memory payload")
        return payload

    async def _get_json(
        self,
        base_url: str,
        path: str,
        *,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"tool-mcp {action} request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"tool-mcp request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("tool-mcp returned non-json payload") from exc

        if not isinstance(payload, dict) or not payload.get("ok"):
            raise RuntimeError(f"tool-mcp returned invalid payload: {payload}")
        return payload

    async def _get_raw_json(
        self,
        base_url: str,
        path: str,
        *,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # memory-service 的 HTTP API 不使用 hub/file-service 的 `{ok, data}` 包装；
        # 单独保留 raw JSON 通道，避免为了一个新服务放宽既有工具边界校验。
        async with httpx.AsyncClient(base_url=base_url, timeout=self._timeout) as client:
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _try_extract_error_detail(exc.response)
                raise RuntimeError(
                    f"tool-mcp {action} request failed: status={exc.response.status_code}, detail={detail}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"tool-mcp request failed: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("tool-mcp returned non-json payload") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"tool-mcp returned invalid payload: {payload}")
        return payload


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
