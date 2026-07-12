import json

import pytest

from tool_mcp_server.mcp_main import create_server, describe_image_object, describe_video_object


class StubToolClient:
    async def get_file_metadata(self, object_key: str):
        if object_key == "b" * 64:
            return {"object_key": object_key, "mime": "video/mp4"}
        return {"object_key": object_key, "mime": "image/jpeg"}

    async def get_file_content(self, object_key: str):
        if object_key == "b" * 64:
            return b"video-bytes"
        return b"image-bytes"


class StubVisionClient:
    def __init__(self) -> None:
        self.calls = []

    async def describe(self, *, content: bytes, mime: str, question: str | None) -> str:
        self.calls.append((content, mime, question))
        return "图片里有一只杯子"

    async def describe_video(self, *, content: bytes, mime: str, question: str | None) -> str:
        self.calls.append((content, mime, question))
        return "视频里有人在挥手"


class StubMemoryClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []

    async def get_user_memory(self, user_id: str, *, start_line: int, line_count: int):
        self.calls.append((user_id, start_line, line_count))
        return {
            "user_id": user_id,
            "content_markdown": "## 用户画像\n",
            "start_line": start_line,
            "line_count": line_count,
            "total_lines": 5,
            "has_more": True,
        }


@pytest.mark.asyncio
async def test_describe_image_object_calls_vision_client() -> None:
    vision = StubVisionClient()

    result = await describe_image_object(
        client=StubToolClient(),  # type: ignore[arg-type]
        vision_client=vision,  # type: ignore[arg-type]
        object_key="a" * 64,
        question="这是什么？",
    )

    assert vision.calls == [(b"image-bytes", "image/jpeg", "这是什么？")]
    assert result == {
        "type": "image_description",
        "object_key": "a" * 64,
        "mime": "image/jpeg",
        "description": "图片里有一只杯子",
        "question": "这是什么？",
        "answer": "图片里有一只杯子",
    }


@pytest.mark.asyncio
async def test_describe_video_object_calls_vision_client() -> None:
    vision = StubVisionClient()

    result = await describe_video_object(
        client=StubToolClient(),  # type: ignore[arg-type]
        vision_client=vision,  # type: ignore[arg-type]
        object_key="b" * 64,
        question="视频里发生了什么？",
    )

    assert vision.calls == [(b"video-bytes", "video/mp4", "视频里发生了什么？")]
    assert result == {
        "type": "video_description",
        "object_key": "b" * 64,
        "mime": "video/mp4",
        "description": "视频里有人在挥手",
        "question": "视频里发生了什么？",
        "answer": "视频里有人在挥手",
    }


@pytest.mark.asyncio
async def test_memory_get_user_memory_tool_passes_pagination_params(monkeypatch) -> None:
    stub_client = StubMemoryClient()

    class DummySettings:
        class Mcp:
            hub_base_url = "http://hub"
            file_base_url = "http://file"
            memory_base_url = "http://memory"
            timeout_seconds = 5.0

        class Server:
            host = "0.0.0.0"
            port = 8030

        class Vision:
            pass

        mcp = Mcp()
        server = Server()
        vision = Vision()

    monkeypatch.setattr("tool_mcp_server.mcp_main.get_settings", lambda: DummySettings())
    monkeypatch.setattr("tool_mcp_server.mcp_main.ToolMcpClient", lambda **kwargs: stub_client)
    monkeypatch.setattr("tool_mcp_server.mcp_main.VisionClient", lambda settings: object())

    server = create_server()
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "memory_get_user_memory")
    result = await tool.fn(user_id="123", start_line=2, line_count=3)

    assert stub_client.calls == [("123", 2, 3)]
    assert json.loads(result) == {
        "user_id": "123",
        "content_markdown": "## 用户画像\n",
        "start_line": 2,
        "line_count": 3,
        "total_lines": 5,
        "has_more": True,
    }


@pytest.mark.asyncio
async def test_memory_get_user_memory_tool_rejects_invalid_pagination(monkeypatch) -> None:
    class DummySettings:
        class Mcp:
            hub_base_url = "http://hub"
            file_base_url = "http://file"
            memory_base_url = "http://memory"
            timeout_seconds = 5.0

        class Server:
            host = "0.0.0.0"
            port = 8030

        class Vision:
            pass

        mcp = Mcp()
        server = Server()
        vision = Vision()

    monkeypatch.setattr("tool_mcp_server.mcp_main.get_settings", lambda: DummySettings())
    monkeypatch.setattr("tool_mcp_server.mcp_main.ToolMcpClient", lambda **kwargs: StubMemoryClient())
    monkeypatch.setattr("tool_mcp_server.mcp_main.VisionClient", lambda settings: object())

    server = create_server()
    tool = next(tool for tool in server._tool_manager.list_tools() if tool.name == "memory_get_user_memory")

    with pytest.raises(ValueError, match="start_line must be non-negative"):
        await tool.fn(user_id="123", start_line=-1, line_count=3)

    with pytest.raises(ValueError, match="line_count must be positive"):
        await tool.fn(user_id="123", start_line=0, line_count=0)
