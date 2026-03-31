from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

import mcp.types as mcp_types
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model


SyncToolExecutor = Callable[[dict[str, Any]], str]
AsyncToolExecutor = Callable[[dict[str, Any]], Awaitable[str]]


def build_mcp_structured_tool(
    *,
    wrapped_name: str,
    server_name: str,
    source_tool: mcp_types.Tool,
    sync_executor: SyncToolExecutor,
    async_executor: AsyncToolExecutor,
) -> StructuredTool:
    """
    将 MCP Tool 元数据包装成 LangChain StructuredTool。

    包装后的工具具备两种执行形态：
    - 同步 `func`：供当前同步 Agent 链路使用；
    - 异步 `coroutine`：供未来全异步链路使用。
    """
    args_schema = build_args_schema(
        tool_name=wrapped_name,
        input_schema=source_tool.inputSchema,
    )
    description = _build_tool_description(
        server_name=server_name,
        source_tool=source_tool,
    )

    def _sync_tool_callable(**kwargs: Any) -> str:
        return sync_executor(kwargs)

    async def _async_tool_callable(**kwargs: Any) -> str:
        return await async_executor(kwargs)

    return StructuredTool.from_function(
        name=wrapped_name,
        description=description,
        args_schema=args_schema,
        func=_sync_tool_callable,
        coroutine=_async_tool_callable,
    )


def build_args_schema(
    *,
    tool_name: str,
    input_schema: dict[str, Any] | None,
) -> type[BaseModel]:
    """
    基于 MCP Tool 的 JSON Schema 动态构建 Pydantic 参数模型。

    约束策略：
    - 仅处理对象型 schema；
    - 非法 Python 字段名直接跳过；
    - 未识别类型回退为 Any。
    """
    if not isinstance(input_schema, dict):
        return _create_empty_args_model(tool_name)

    properties = input_schema.get("properties")
    if not isinstance(properties, dict):
        return _create_empty_args_model(tool_name)

    raw_required = input_schema.get("required")
    required_fields = set(raw_required) if isinstance(raw_required, list) else set()
    model_fields: dict[str, tuple[Any, Any]] = {}

    for raw_field_name, raw_field_schema in properties.items():
        field_name = str(raw_field_name).strip()
        if not _is_valid_python_field_name(field_name):
            continue

        field_schema = raw_field_schema if isinstance(raw_field_schema, dict) else {}
        field_type = json_schema_type_to_python(field_schema)
        field_description = field_schema.get("description")
        description_value = (
            str(field_description)
            if isinstance(field_description, str) and field_description.strip()
            else None
        )

        if field_name in required_fields:
            model_fields[field_name] = (
                field_type,
                Field(default=..., description=description_value),
            )
        else:
            model_fields[field_name] = (
                field_type | None,
                Field(default=None, description=description_value),
            )

    if not model_fields:
        return _create_empty_args_model(tool_name)

    model_name = f"{_to_model_name(tool_name)}Args"
    return create_model(model_name, **model_fields)


def parse_call_tool_result(result: mcp_types.CallToolResult) -> str:
    """
    解析 MCP call_tool 返回值并输出统一字符串。

    解析规则：
    1. 优先拼接全部 TextContent；
    2. 非文本内容转为可读占位文本；
    3. isError=True 时抛出异常。
    """
    text_segments: list[str] = []
    fallback_segments: list[str] = []

    for content in result.content:
        if isinstance(content, mcp_types.TextContent):
            text_segments.append(content.text)
            continue
        fallback_segments.append(_render_non_text_content(content))

    response_text = "\n".join(segment for segment in text_segments if segment.strip())
    if not response_text:
        response_text = "\n".join(segment for segment in fallback_segments if segment.strip())

    if not response_text:
        if result.structuredContent is not None:
            response_text = json.dumps(result.structuredContent, ensure_ascii=False)
        else:
            response_text = "[MCP Tool] 未返回可读文本内容。"

    if result.isError:
        raise RuntimeError(response_text)

    return response_text


def json_schema_type_to_python(field_schema: dict[str, Any]) -> Any:
    """将 JSON Schema 类型映射到 Python 类型。"""
    raw_type = field_schema.get("type")

    if isinstance(raw_type, list):
        # 兼容 ["string", "null"] 这种联合声明，优先取首个非 null。
        non_null = [item for item in raw_type if item != "null"]
        raw_type = non_null[0] if non_null else "null"

    if raw_type == "string":
        return str
    if raw_type == "integer":
        return int
    if raw_type == "number":
        return float
    if raw_type == "boolean":
        return bool
    if raw_type == "array":
        return list[Any]
    if raw_type == "object":
        return dict[str, Any]
    return Any


def _build_tool_description(*, server_name: str, source_tool: mcp_types.Tool) -> str:
    raw_description = source_tool.description or "MCP 动态工具"
    return (
        f"{raw_description}\n\n"
        f"[MCP 来源] server={server_name}, tool={source_tool.name}"
    )


def _render_non_text_content(content: mcp_types.ContentBlock) -> str:
    if isinstance(content, mcp_types.ImageContent):
        return f"[image content] mimeType={content.mimeType}"

    if isinstance(content, mcp_types.AudioContent):
        return f"[audio content] mimeType={content.mimeType}"

    if isinstance(content, mcp_types.ResourceLink):
        return f"[resource link] uri={content.uri}"

    if isinstance(content, mcp_types.EmbeddedResource):
        resource = content.resource
        if isinstance(resource, mcp_types.TextResourceContents):
            return f"[embedded text resource] uri={resource.uri}"
        if isinstance(resource, mcp_types.BlobResourceContents):
            return f"[embedded blob resource] uri={resource.uri}, mimeType={resource.mimeType}"
        return "[embedded resource]"

    return "[unknown content block]"


def _is_valid_python_field_name(field_name: str) -> bool:
    if not field_name:
        return False
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", field_name):
        return False
    return True


def _to_model_name(tool_name: str) -> str:
    clean_name = re.sub(r"[^A-Za-z0-9_]+", "_", tool_name).strip("_")
    if not clean_name:
        clean_name = "McpTool"
    if clean_name[0].isdigit():
        clean_name = f"Tool_{clean_name}"
    return "".join(part.capitalize() for part in clean_name.split("_"))


def _create_empty_args_model(tool_name: str) -> type[BaseModel]:
    model_name = f"{_to_model_name(tool_name)}EmptyArgs"
    return create_model(model_name)
