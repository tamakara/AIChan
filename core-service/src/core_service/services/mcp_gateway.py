import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

import mcp.types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


@dataclass(frozen=True)
class McpToolBinding:
    remote_name: str
    description: str
    input_schema: dict[str, Any]


class McpToolClient:
    _UNSUPPORTED_SCHEMA_KEYS = {"propertyNames"}

    def __init__(self, sse_url: str, auth_token: str | None = None) -> None:
        self._sse_url = sse_url
        self._auth_token = auth_token
        self._tools: dict[str, McpToolBinding] = {}
        self.ready = False

    async def initialize(self) -> None:
        async with self._session() as session:
            result = await session.list_tools()
        tools: dict[str, McpToolBinding] = {}
        for remote in result.tools:
            tools[remote.name] = McpToolBinding(
                remote_name=remote.name,
                description=remote.description or "MCP tool",
                input_schema=self._normalize_schema(remote.inputSchema),
            )
        self._tools = tools
        self.ready = True

    @property
    def tool_names(self) -> set[str]:
        return set(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": name, "description": item.description, "parameters": item.input_schema}}
            for name, item in self._tools.items()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        binding = self._tools.get(name)
        if binding is None:
            raise KeyError(f"未找到 MCP 工具: {name}")
        async with self._session() as session:
            result = await session.call_tool(binding.remote_name, arguments)
        return json.dumps(result.model_dump(by_alias=True, mode="json", exclude_none=True), ensure_ascii=False)

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[ClientSession]:
        headers = {"Authorization": f"Bearer {self._auth_token}"} if self._auth_token else None
        async with sse_client(self._sse_url, headers=headers) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session

    def _normalize_schema(self, schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        cleaned = self._sanitize(schema)
        cleaned.setdefault("type", "object")
        if cleaned["type"] == "object":
            cleaned.setdefault("properties", {})
        return cleaned

    def _sanitize(self, node: Any) -> Any:
        if isinstance(node, dict):
            return {key: self._sanitize(value) for key, value in node.items() if key not in self._UNSUPPORTED_SCHEMA_KEYS}
        if isinstance(node, list):
            return [self._sanitize(item) for item in node]
        return node
