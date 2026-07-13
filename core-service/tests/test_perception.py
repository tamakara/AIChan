from pathlib import Path

import pytest

from core_service.config import PerceptionSettings
from core_service.services.file_cache import CachedFile
from core_service.services.perception import FilePerceptionRouter, PerceptionClient, classify_file, effective_mime_type


class StubPerceptionClient:
    async def describe_image(self, **kwargs):
        return "image description"

    async def describe_video(self, **kwargs):
        return "video description"

    async def transcribe_audio(self, **kwargs):
        return "audio transcript"


@pytest.mark.parametrize(("mime", "name", "expected"), [
    ("text/plain", "x.bin", "text"),
    ("application/octet-stream", "x.md", "text"),
    ("image/png", "x", "image"),
    ("audio/ogg", "x", "audio"),
    ("video/mp4", "x", "video"),
    ("application/zip", "x.zip", "binary"),
])
def test_classify_file(mime: str, name: str, expected: str) -> None:
    assert classify_file(effective_mime_type(mime, name), name) == expected


def test_effective_mime_uses_filename_when_adapter_returns_generic_type() -> None:
    assert effective_mime_type("application/octet-stream", "photo.jpg") == "image/jpeg"


@pytest.mark.asyncio
async def test_perception_router_returns_uniform_results(tmp_path: Path) -> None:
    router = FilePerceptionRouter(StubPerceptionClient())
    path = tmp_path / "content"
    path.write_text("abcdef", encoding="utf-8")
    text = await router.perceive(CachedFile("text-ref", path, "a.txt", "text/plain", 6), question=None, max_chars=3)
    assert text["content"] == "abc" and text["truncated"] is True and text["content_kind"] == "text"
    image = await router.perceive(CachedFile("image-ref", path, "a.png", "image/png", 6), question="what", max_chars=3)
    assert image["content"] == "image description" and image["content_kind"] == "description"
    audio = await router.perceive(CachedFile("audio-ref", path, "a.ogg", "audio/ogg", 6), question=None, max_chars=3)
    assert audio["content"] == "audio transcript" and audio["content_kind"] == "transcript"
    binary = await router.perceive(CachedFile("bin-ref", path, "a.zip", "application/zip", 6), question=None, max_chars=3)
    assert binary["supported"] is False and binary["content"] is None


@pytest.mark.asyncio
async def test_audio_transcription_uses_audio_model_and_prompt() -> None:
    calls = []

    class Transcriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return type("Response", (), {"text": "hello"})()

    class StubOpenAI:
        audio = type("Audio", (), {"transcriptions": Transcriptions()})()

    client = PerceptionClient(PerceptionSettings(openai_base_url="http://localhost", openai_api_key="key", visual_model="vision", audio_model="whisper-1", timeout_seconds=10, video_frame_count=3))
    client._client = StubOpenAI()  # type: ignore[assignment]
    result = await client.transcribe_audio(content=b"audio", name="a.ogg", mime_type="audio/ogg", question="专有名词 AICHAN")
    assert result == "hello"
    assert calls == [{"model": "whisper-1", "file": ("a.ogg", b"audio", "audio/ogg"), "prompt": "专有名词 AICHAN"}]
