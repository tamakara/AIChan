import pytest

from tool_mcp_server.mcp_main import describe_image_object, describe_video_object


class StubToolClient:
    async def get_file_metadata(self, object_key: str):
        if object_key.endswith(".mp4"):
            return {"object_key": object_key, "mime": "video/mp4"}
        return {"object_key": object_key, "mime": "image/jpeg"}

    async def get_file_content(self, object_key: str):
        if object_key.endswith(".mp4"):
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


@pytest.mark.asyncio
async def test_describe_image_object_calls_vision_client() -> None:
    vision = StubVisionClient()

    result = await describe_image_object(
        client=StubToolClient(),  # type: ignore[arg-type]
        vision_client=vision,  # type: ignore[arg-type]
        object_key="qq/private/1/9/0-abc.jpg",
        question="这是什么？",
    )

    assert vision.calls == [(b"image-bytes", "image/jpeg", "这是什么？")]
    assert result == {
        "type": "image_description",
        "object_key": "qq/private/1/9/0-abc.jpg",
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
        object_key="qq/private/1/9/0-abc.mp4",
        question="视频里发生了什么？",
    )

    assert vision.calls == [(b"video-bytes", "video/mp4", "视频里发生了什么？")]
    assert result == {
        "type": "video_description",
        "object_key": "qq/private/1/9/0-abc.mp4",
        "mime": "video/mp4",
        "description": "视频里有人在挥手",
        "question": "视频里发生了什么？",
        "answer": "视频里有人在挥手",
    }
