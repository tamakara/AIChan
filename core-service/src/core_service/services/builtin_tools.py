from __future__ import annotations

from typing import Any

from ..adapters.registry import AdapterRegistry
from .context_manager import ContextManager
from .file_cache import FileCache
from .memory_client import MemoryClient
from .perception import FilePerceptionRouter


class BuiltinTools:
    def __init__(self, *, adapters: AdapterRegistry, contexts: ContextManager, cache: FileCache, perception: FilePerceptionRouter, memory: MemoryClient | None) -> None:
        self._adapters = adapters
        self._contexts = contexts
        self._cache = cache
        self._perception = perception
        self._memory = memory

    @property
    def names(self) -> set[str]:
        names = {"file_perceive", "message_query"}
        if self._memory is not None:
            names.add("memory_get_user_memory")
        return names

    def schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = [
            _tool_schema(
                "file_perceive",
                "按需获取并识别当前会话中出现过的文件；自动路由文本、图片、音频、视频和普通二进制。",
                {
                    "type": "object",
                    "properties": {
                        "file_ref": {"type": "string", "minLength": 1},
                        "question": {"type": ["string", "null"]},
                        "max_chars": {"type": "integer", "minimum": 1, "maximum": 50000, "default": 12000},
                    },
                    "required": ["file_ref"],
                    "additionalProperties": False,
                },
            ),
            _tool_schema(
                "message_query",
                "分页查询当前会话所属渠道的历史消息；不能跨会话查询。",
                {
                    "type": "object",
                    "properties": {
                        "cursor": {"type": ["string", "null"]},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    },
                    "additionalProperties": False,
                },
            ),
        ]
        if self._memory is not None:
            schemas.append(_tool_schema(
                "memory_get_user_memory",
                "按用户 ID 分页读取长期用户记忆。",
                {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string", "minLength": 1},
                        "start_line": {"type": "integer", "minimum": 0, "default": 0},
                        "line_count": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                    },
                    "required": ["user_id"],
                    "additionalProperties": False,
                },
            ))
        return schemas

    async def call(self, *, name: str, arguments: dict[str, Any], session_id: str, adapter_key: tuple[str, str], metadata: dict[str, Any]) -> Any:
        if name == "file_perceive":
            return await self._file_perceive(arguments, session_id, adapter_key)
        if name == "message_query":
            return await self._message_query(arguments, session_id, adapter_key, metadata)
        if name == "memory_get_user_memory" and self._memory is not None:
            user_id = str(arguments.get("user_id", "")).strip()
            if not user_id:
                raise ValueError("user_id 不能为空")
            return await self._memory.get_user_memory(
                user_id,
                start_line=int(arguments.get("start_line", 0)),
                line_count=int(arguments.get("line_count", 200)),
            )
        raise KeyError(f"未找到 Core 内置工具: {name}")

    async def _file_perceive(self, arguments: dict[str, Any], session_id: str, adapter_key: tuple[str, str]) -> dict[str, Any]:
        file_ref = str(arguments.get("file_ref", ""))
        if not file_ref or not await self._contexts.file_ref_allowed(session_id, file_ref):
            raise ValueError("file_ref 未出现在当前会话上下文中")
        max_chars = int(arguments.get("max_chars", 12000))
        if not 1 <= max_chars <= 50000:
            raise ValueError("max_chars 必须在 1 到 50000 之间")
        question_value = arguments.get("question")
        question = str(question_value) if question_value is not None else None
        base_url, token = self._adapters.file_source(adapter_key)
        cached = await self._cache.get(adapter_key=adapter_key, file_ref=file_ref, base_url=base_url, token=token)
        return await self._perception.perceive(cached, question=question, max_chars=max_chars)

    async def _message_query(self, arguments: dict[str, Any], session_id: str, adapter_key: tuple[str, str], metadata: dict[str, Any]) -> dict[str, Any]:
        limit = int(arguments.get("limit", 20))
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1 到 100 之间")
        cursor_value = arguments.get("cursor")
        cursor = str(cursor_value) if cursor_value is not None else None
        result, file_refs = await self._adapters.query_messages(
            adapter_key,
            session_id=session_id,
            conversation_type=str(metadata["conversation_type"]),
            conversation_id=str(metadata["conversation_id"]),
            cursor=cursor,
            limit=limit,
        )
        await self._contexts.add_file_refs(session_id, file_refs)
        return result.model_dump()


def _tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
