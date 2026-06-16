from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any

import cv2
from openai import AsyncOpenAI

from .config import VisionSettings


class VisionClient:
    """独立视觉模型边界，后续可替换为更适合图片理解的供应商或模型。"""

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    async def describe(self, *, content: bytes, mime: str, question: str | None) -> str:
        client = self._openai_client()
        prompt = question or "请描述这张图片中的主要内容、文字、人物、物体和可能的上下文。"
        encoded = base64.b64encode(content).decode("ascii")
        response = await client.chat.completions.create(
            model=self._settings.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{encoded}"},
                        },
                    ],
                }
            ],
        )
        message = response.choices[0].message.content
        return message or ""

    async def describe_video(self, *, content: bytes, mime: str, question: str | None) -> str:
        client = self._openai_client()
        # 多数 OpenAI-compatible vision 接口对 video_url 支持不一致；工具侧抽帧后按图片输入，
        # 可以复用现有视觉模型能力，并把视频理解的 token/带宽上限控制在配置内。
        frames = _sample_video_frames(
            content=content,
            mime=mime,
            frame_count=self._settings.video_frame_count,
        )
        prompt = question or (
            "请根据抽取的视频画面描述视频主要内容、人物、物体、文字、场景变化和可能的上下文。"
        )
        content_parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": f"{prompt}\n\n下面是从视频中按时间顺序抽取的 {len(frames)} 帧画面。",
            }
        ]
        for frame in frames:
            encoded = base64.b64encode(frame).decode("ascii")
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
            )

        response = await client.chat.completions.create(
            model=self._settings.model,
            messages=[{"role": "user", "content": content_parts}],
        )
        message = response.choices[0].message.content
        return message or ""

    def _openai_client(self) -> AsyncOpenAI:
        if not self._settings.openai_api_key or not self._settings.model:
            raise RuntimeError("vision.openai_api_key and vision.model are required")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
                timeout=self._settings.timeout_seconds,
            )
        return self._client


def _sample_video_frames(*, content: bytes, mime: str, frame_count: int) -> list[bytes]:
    suffix = _video_suffix(mime)
    path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_file.write(content)
            path = temp_file.name

        capture = cv2.VideoCapture(path)
        try:
            if not capture.isOpened():
                raise ValueError("无法解码视频")

            total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames > 0:
                frames = _read_indexed_frames(capture, _sample_indices(total_frames, frame_count))
            else:
                frames = _read_sequential_frames(capture, frame_count)
        finally:
            capture.release()
    finally:
        if path:
            Path(path).unlink(missing_ok=True)

    if not frames:
        raise ValueError("无法从视频中抽取画面")
    return frames


def _read_indexed_frames(capture: cv2.VideoCapture, indices: list[int]) -> list[bytes]:
    frames: list[bytes] = []
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if not ok:
            continue
        frames.append(_encode_frame(frame))
    return frames


def _read_sequential_frames(capture: cv2.VideoCapture, frame_count: int) -> list[bytes]:
    frames: list[bytes] = []
    while len(frames) < frame_count:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(_encode_frame(frame))
    return frames


def _encode_frame(frame: Any) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise ValueError("无法编码视频画面")
    return encoded.tobytes()


def _sample_indices(total_frames: int, frame_count: int) -> list[int]:
    if total_frames <= 1 or frame_count <= 1:
        return [0]
    count = min(total_frames, frame_count)
    step = (total_frames - 1) / (count - 1)
    return sorted({round(index * step) for index in range(count)})


def _video_suffix(mime: str) -> str:
    ext = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
    }.get(mime)
    if ext:
        return ext
    guessed = os.path.splitext(mime.rsplit("/", 1)[-1])[1]
    return guessed or ".mp4"
