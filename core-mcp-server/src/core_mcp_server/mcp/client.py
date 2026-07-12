from __future__ import annotations

import json
from typing import Any

import httpx


class CoreMcpClient:
    """复用下游连接，避免每次 MCP 调用重复创建连接池。"""

    def __init__(self, file_base_url: str, memory_base_url: str, timeout_seconds: float) -> None:
        self._file = httpx.AsyncClient(base_url=file_base_url.rstrip("/"), timeout=timeout_seconds)
        self._memory = httpx.AsyncClient(base_url=memory_base_url.rstrip("/"), timeout=timeout_seconds)

    async def get_file_metadata(self, object_key: str) -> dict[str, Any]:
        payload = await self._request_json(self._file, f"/api/v1/files/{object_key}/metadata", wrapped=True)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("core-mcp-server 收到非法文件元数据")
        return data

    async def read_file_text(self, object_key: str, max_chars: int) -> dict[str, Any]:
        payload = await self._request_json(self._file, f"/api/v1/files/{object_key}/text", params={"max_chars": max_chars}, wrapped=True)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("core-mcp-server 收到非法文本响应")
        return data

    async def get_file_content(self, object_key: str) -> bytes:
        response = await self._file.get(f"/api/v1/files/{object_key}/content")
        self._raise(response)
        return response.content

    async def get_user_memory(self, user_id: str, *, start_line: int, line_count: int) -> dict[str, Any]:
        payload = await self._request_json(self._memory, f"/api/v1/users/{user_id}/memory", params={"start_line": start_line, "line_count": line_count}, wrapped=False)
        required = {"user_id": str, "content_markdown": str, "start_line": int, "line_count": int, "total_lines": int, "has_more": bool}
        if any(not isinstance(payload.get(key), kind) for key, kind in required.items()):
            raise RuntimeError("core-mcp-server 收到非法用户记忆响应")
        return payload

    async def close(self) -> None:
        await self._file.aclose()
        await self._memory.aclose()

    async def _request_json(self, client: httpx.AsyncClient, path: str, *, params: dict[str, Any] | None = None, wrapped: bool) -> dict[str, Any]:
        response = await client.get(path, params=params)
        self._raise(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("core-mcp-server 收到非 JSON 响应") from exc
        if not isinstance(payload, dict) or (wrapped and not payload.get("ok")):
            raise RuntimeError(f"core-mcp-server 收到非法响应: {payload}")
        return payload

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = json.dumps(response.json(), ensure_ascii=False)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"下游请求失败: status={response.status_code}, detail={detail}") from exc
