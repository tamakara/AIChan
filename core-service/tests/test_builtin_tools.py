from pathlib import Path

import pytest

from core_service.adapters.protocol import MessageQueryResult
from core_service.services.builtin_tools import BuiltinTools
from core_service.services.file_cache import CachedFile


class StubAdapters:
    def __init__(self) -> None:
        self.query_args = None

    def file_source(self, key):
        return "http://adapter/files", "token"

    async def query_messages(self, key, **kwargs):
        self.query_args = (key, kwargs)
        return MessageQueryResult(messages_xml='<messages><message id="1" timestamp="1" sender_id="u"><text>old</text></message></messages>', has_more=False), frozenset({"history-file"})


class StubContexts:
    def __init__(self) -> None:
        self.refs = {"current-file"}

    async def file_ref_allowed(self, session_id, file_ref):
        return file_ref in self.refs

    async def add_file_refs(self, session_id, refs):
        self.refs.update(refs)


class StubCache:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def get(self, **kwargs):
        return CachedFile(kwargs["file_ref"], self.path, "a.txt", "text/plain", self.path.stat().st_size)


class StubPerception:
    async def perceive(self, cached, **kwargs):
        return {"file_ref": cached.file_ref, "content": "hello"}


class StubMemory:
    async def get_user_memory(self, user_id, **kwargs):
        return {"user_id": user_id, "content_markdown": "memory"}


@pytest.mark.asyncio
async def test_builtin_tools_scope_files_and_message_query_to_current_session(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello", encoding="utf-8")
    adapters = StubAdapters()
    contexts = StubContexts()
    tools = BuiltinTools(adapters=adapters, contexts=contexts, cache=StubCache(path), perception=StubPerception(), memory=StubMemory())
    assert {item["function"]["name"] for item in tools.schemas()} == {"file_perceive", "message_query", "memory_get_user_memory"}
    perceived = await tools.call(name="file_perceive", arguments={"file_ref": "current-file"}, session_id="s", adapter_key=("qq", "main"), metadata={"conversation_type": "group", "conversation_id": "1"})
    assert perceived["content"] == "hello"
    with pytest.raises(ValueError, match="未出现在"):
        await tools.call(name="file_perceive", arguments={"file_ref": "other"}, session_id="s", adapter_key=("qq", "main"), metadata={})
    result = await tools.call(name="message_query", arguments={"limit": 10}, session_id="s", adapter_key=("qq", "main"), metadata={"conversation_type": "group", "conversation_id": "1"})
    assert result["has_more"] is False
    assert adapters.query_args[1]["conversation_id"] == "1"
    assert "history-file" in contexts.refs


@pytest.mark.asyncio
async def test_builtin_memory_tool_uses_memory_client(tmp_path: Path) -> None:
    tools = BuiltinTools(adapters=StubAdapters(), contexts=StubContexts(), cache=StubCache(tmp_path), perception=StubPerception(), memory=StubMemory())
    result = await tools.call(name="memory_get_user_memory", arguments={"user_id": "u1"}, session_id="s", adapter_key=("qq", "main"), metadata={})
    assert result == {"user_id": "u1", "content_markdown": "memory"}
