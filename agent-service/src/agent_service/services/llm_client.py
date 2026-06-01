from typing import List, cast

from openai import OpenAI

from .types import Message, LlmResponse, ToolCall


class LlmClient:
    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
    ):
        self._model_name = model_name
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(
        self,
        messages: List[Message],
        tools_schema: List,
        temperature: float,
    ) -> LlmResponse:
        response = self._client.chat.completions.create(
            messages=messages,
            model=self._model_name,
            temperature=temperature,
            tool_choice="auto",
            tools=tools_schema,
        )

        content = response.choices[0].message.content or ""
        tool_calls = cast(
            List[ToolCall], response.choices[0].message.tool_calls or []
        )
        finish_reason = response.choices[0].finish_reason

        return LlmResponse(
            content=content, tool_calls=tool_calls, finish_reason=finish_reason
        )
