from __future__ import annotations

import base64

from openai import AsyncOpenAI

from .config import VisionSettings


class VisionClient:
    """独立视觉模型边界，后续可替换为更适合图片理解的供应商或模型。"""

    def __init__(self, settings: VisionSettings) -> None:
        self._settings = settings
        self._client: AsyncOpenAI | None = None

    async def describe(self, *, content: bytes, mime: str, question: str | None) -> str:
        if not self._settings.openai_api_key or not self._settings.model:
            raise RuntimeError("vision.openai_api_key and vision.model are required")
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key,
                base_url=self._settings.openai_base_url or None,
                timeout=self._settings.timeout_seconds,
            )
        prompt = question or "请描述这张图片中的主要内容、文字、人物、物体和可能的上下文。"
        encoded = base64.b64encode(content).decode("ascii")
        response = await self._client.chat.completions.create(
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
