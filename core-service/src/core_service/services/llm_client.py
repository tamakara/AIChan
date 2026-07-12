from typing import cast

from openai import AsyncOpenAI

from .types.llm import LlmResponse, Message, ToolCall


class LlmClient:
    def __init__(self, model_name: str, api_key: str, base_url: str, timeout: float, max_retries: int) -> None:
        self._model_name = model_name
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=max_retries)

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, messages: list[Message], tools_schema: list[dict], temperature: float) -> LlmResponse:
        arguments = {
            "messages": messages,
            "model": self._model_name,
            "temperature": temperature,
        }
        if tools_schema:
            arguments["tool_choice"] = "auto"
            arguments["tools"] = tools_schema
        response = await self._client.chat.completions.create(  # type: ignore[arg-type]
            **arguments,
        )
        choice = response.choices[0]
        return LlmResponse(
            content=choice.message.content or "",
            tool_calls=cast(list[ToolCall], choice.message.tool_calls or []),
            finish_reason=choice.finish_reason,
        )

    async def close(self) -> None:
        await self._client.close()
