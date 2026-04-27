import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List

import anyio
import mcp.types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client


@dataclass(frozen=True)
class McpToolBinding:
    remote_name: str
    description: str
    input_schema: Dict[str, Any]


class ToolRegistry:
    def __init__(self, sse_url: str, bearer_token: str | None = None):
        self._sse_url = sse_url
        self._bearer_token = bearer_token
        self._mcp_tools: Dict[str, McpToolBinding] = {}
        self._tools_schema: List[Dict[str, Any]] = []

    def register_mcp_server(self) -> None:
        try:
            remote_tools = anyio.run(self._list_mcp_tools_async)
        except Exception as exc:
            raise RuntimeError("连接 MCP SSE 服务失败") from exc

        # 启动阶段把远端工具元数据固化为本地映射，后续只按名称检索，避免每轮请求都拉取工具列表。
        for remote_tool in remote_tools:
            self._mcp_tools[remote_tool.name] = McpToolBinding(
                remote_name=remote_tool.name,
                description=remote_tool.description or "MCP tool from SSE Gateway",
                input_schema=self._normalize_schema(remote_tool.inputSchema),
            )
        self._refresh_tools_schema()

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        return self._tools_schema

    def call_tool(self, tool_name: str, tool_args: Dict[str, Any]) -> str:
        binding = self._mcp_tools.get(tool_name)
        if binding is None:
            raise KeyError(f"未找到工具: {tool_name}")
        if not isinstance(tool_args, dict):
            raise TypeError(f"工具参数必须是 dict，当前为: {type(tool_args)}")

        try:
            result = anyio.run(
                self._call_mcp_tool_async, binding.remote_name, tool_args
            )
        except Exception as exc:
            raise RuntimeError(f"调用 MCP SSE 工具失败: {exc}") from exc

        return json.dumps(
            result.model_dump(by_alias=True, mode="json", exclude_none=True),
            ensure_ascii=False,
        )

    def _refresh_tools_schema(self) -> None:
        # 预先构造 OpenAI 函数调用协议所需 schema，减少运行时重复拼装开销。
        self._tools_schema = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": binding.description,
                    "parameters": binding.input_schema,
                },
            }
            for name, binding in self._mcp_tools.items()
        ]

    async def _list_mcp_tools_async(self) -> List[mcp_types.Tool]:
        async with self._mcp_session() as session:
            result = await session.list_tools()
            return result.tools

    async def _call_mcp_tool_async(
        self, remote_tool_name: str, tool_args: Dict[str, Any]
    ) -> mcp_types.CallToolResult:
        async with self._mcp_session() as session:
            return await session.call_tool(name=remote_tool_name, arguments=tool_args)

    @asynccontextmanager
    async def _mcp_session(self) -> AsyncIterator[ClientSession]:
        headers = (
            {"Authorization": f"Bearer {self._bearer_token}"}
            if self._bearer_token
            else None
        )
        async with sse_client(self._sse_url, headers=headers) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                yield session

    @staticmethod
    def _normalize_schema(schema: Any) -> Dict[str, Any]:
        # 部分 MCP 工具返回的 schema 可能缺少 type/properties，这里兜底为 object，
        # 避免上游 LLM 在函数调用阶段因参数协议不完整而拒绝生成调用。
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        out = dict(schema)
        if "type" not in out:
            out["type"] = "object"
        if out["type"] == "object" and "properties" not in out:
            out["properties"] = {}
        return out
