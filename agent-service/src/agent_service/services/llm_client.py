from typing import List, cast

from openai import OpenAI
from openai import APIStatusError

from ..logger import get_logger, log_error, log_exception
from .observability import Observability
from .types import Message, LlmResponse, ToolCall


class LlmClient:
    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str,
        observability: Observability,
    ):
        self._logger = get_logger("llm_client")
        self._model_name = model_name
        self._observability = observability
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(
        self,
        messages: List[Message],
        tools_schema: List,
        temperature: float,
    ) -> LlmResponse:
        try:
            request_payload = {
                "messages": messages,
                "model": self._model_name,
                "temperature": temperature,
                "tool_choice": "auto",
                "tools": tools_schema,
            }

            response = self._client.chat.completions.create(**request_payload)

            content = response.choices[0].message.content or ""
            tool_calls = cast(
                List[ToolCall], response.choices[0].message.tool_calls or []
            )
            finish_reason = response.choices[0].finish_reason

            return LlmResponse(
                content=content, tool_calls=tool_calls, finish_reason=finish_reason
            )
        except APIStatusError as e:
            log_error(
                self._logger,
                "llm.request_failed",
                status_code=e.status_code,
                model=self._model_name,
                detail=e.response.text if e.response is not None else str(e),
            )
            raise RuntimeError(
                f"LLM 请求失败: status={e.status_code}, detail={e.response.text if e.response is not None else e}"
            )
        except Exception as e:
            log_exception(
                self._logger,
                "llm.request_failed",
                model=self._model_name,
                error=e,
            )
            raise RuntimeError(f"LLM 请求失败: {e}")
