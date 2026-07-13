from __future__ import annotations

import base64
import mimetypes
import os
import tempfile
from pathlib import Path, PurePath
from typing import Any, Literal

import cv2
from openai import AsyncOpenAI

from ..config import PerceptionSettings
from .file_cache import CachedFile

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".json", ".xml", ".yaml", ".yml", ".csv", ".tsv", ".log", ".py", ".js", ".ts", ".html", ".css", ".toml", ".ini"}
FileType = Literal["text", "image", "audio", "video", "binary"]


class PerceptionClient:
    def __init__(self, settings: PerceptionSettings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    async def describe_image(self, *, content: bytes, mime_type: str, question: str | None) -> str:
        client = self._require_client(self._settings.visual_model, "visual_model")
        encoded = base64.b64encode(content).decode("ascii")
        response = await client.chat.completions.create(
            model=self._settings.visual_model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": question or "请描述图片的主要内容、文字、人物、物体和上下文。"},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ]}],
        )
        return response.choices[0].message.content or ""

    async def describe_video(self, *, content: bytes, mime_type: str, question: str | None) -> str:
        client = self._require_client(self._settings.visual_model, "visual_model")
        frames = _sample_video_frames(content=content, mime_type=mime_type, frame_count=self._settings.video_frame_count)
        parts: list[dict[str, Any]] = [{"type": "text", "text": question or "请根据按时间顺序抽取的画面描述视频内容和场景变化。"}]
        for frame in frames:
            encoded = base64.b64encode(frame).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}})
        response = await client.chat.completions.create(model=self._settings.visual_model, messages=[{"role": "user", "content": parts}])
        return response.choices[0].message.content or ""

    async def transcribe_audio(self, *, content: bytes, name: str, mime_type: str, question: str | None) -> str:
        client = self._require_client(self._settings.audio_model, "audio_model")
        arguments: dict[str, Any] = {
            "model": self._settings.audio_model,
            "file": (name, content, mime_type),
        }
        if question:
            arguments["prompt"] = question
        response = await client.audio.transcriptions.create(  # type: ignore[arg-type]
            **arguments,
        )
        return response.text

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    def _require_client(self, model: str, label: str) -> AsyncOpenAI:
        if not self._settings.openai_api_key or not model:
            raise RuntimeError(f"perception openai_api_key 和 {label} 必须配置")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
                timeout=self._settings.timeout_seconds,
            )
        return self._client


class FilePerceptionRouter:
    def __init__(self, client: PerceptionClient) -> None:
        self._client = client

    async def perceive(self, cached: CachedFile, *, question: str | None, max_chars: int) -> dict[str, Any]:
        mime_type = effective_mime_type(cached.mime_type, cached.name)
        file_type = classify_file(mime_type, cached.name)
        content: str | None = None
        content_kind: str | None = None
        truncated = False
        supported = file_type != "binary"
        if file_type == "text":
            raw = cached.path.read_bytes().decode("utf-8-sig", errors="replace")
            content = raw[:max_chars]
            truncated = len(raw) > max_chars
            content_kind = "text"
        elif file_type == "image":
            content = await self._client.describe_image(content=cached.path.read_bytes(), mime_type=mime_type, question=question)
            content_kind = "description"
        elif file_type == "video":
            content = await self._client.describe_video(content=cached.path.read_bytes(), mime_type=mime_type, question=question)
            content_kind = "description"
        elif file_type == "audio":
            content = await self._client.transcribe_audio(content=cached.path.read_bytes(), name=cached.name, mime_type=mime_type, question=question)
            content_kind = "transcript"
        return {
            "file_ref": cached.file_ref,
            "name": cached.name,
            "mime_type": mime_type,
            "size": cached.size,
            "file_type": file_type,
            "supported": supported,
            "content_kind": content_kind,
            "content": content,
            "truncated": truncated,
        }


def classify_file(mime_type: str, name: str) -> FileType:
    mime = mime_type.lower()
    if mime.startswith("text/") or PurePath(name).suffix.lower() in TEXT_EXTENSIONS:
        return "text"
    for prefix, file_type in (("image/", "image"), ("audio/", "audio"), ("video/", "video")):
        if mime.startswith(prefix):
            return file_type  # type: ignore[return-value]
    return "binary"


def effective_mime_type(mime_type: str, name: str) -> str:
    normalized = mime_type.split(";", 1)[0].strip().lower()
    if normalized and normalized not in {"application/octet-stream", "binary/octet-stream", "application/x-octet-stream"}:
        return normalized
    guessed, _ = mimetypes.guess_type(name)
    return guessed or normalized or "application/octet-stream"


def _sample_video_frames(*, content: bytes, mime_type: str, frame_count: int) -> list[bytes]:
    path = ""
    frames: list[bytes] = []
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=_video_suffix(mime_type)) as temporary:
            temporary.write(content)
            path = temporary.name
        capture = cv2.VideoCapture(path)
        try:
            if not capture.isOpened():
                raise ValueError("无法解码视频")
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            indices = _sample_indices(total, frame_count) if total > 0 else list(range(frame_count))
            for index in indices:
                if total > 0:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = capture.read()
                if not ok:
                    continue
                encoded_ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
                if encoded_ok:
                    frames.append(encoded.tobytes())
        finally:
            capture.release()
    finally:
        if path:
            Path(path).unlink(missing_ok=True)
    if not frames:
        raise ValueError("无法从视频中抽取画面")
    return frames


def _sample_indices(total: int, count: int) -> list[int]:
    if total <= 1 or count <= 1:
        return [0]
    actual = min(total, count)
    step = (total - 1) / (actual - 1)
    return sorted({round(index * step) for index in range(actual)})


def _video_suffix(mime_type: str) -> str:
    return {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv", "video/webm": ".webm"}.get(mime_type, os.path.splitext(mime_type.rsplit("/", 1)[-1])[1] or ".mp4")
