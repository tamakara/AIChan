from typing import List, Literal

from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
)
from pydantic import BaseModel

type LlmMessage = ChatCompletionMessageParam
type ToolCall = ChatCompletionMessageFunctionToolCall


class LlmResponse(BaseModel):
    content: str
    tool_calls: List[ToolCall]
    finish_reason: Literal[
        "stop", "length", "tool_calls", "content_filter", "function_call"
    ]
