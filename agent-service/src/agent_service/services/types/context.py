from typing import cast

from .llm import Message, ToolCall


class Context:
    def __init__(self, messages: list[Message] | None = None) -> None:
        self.messages: list[Message] = messages or []

    def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[ToolCall] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        # 把 OpenAI 消息结构写入集中到 Context，避免调用方各自拼装导致字段漂移。
        message_dict: dict[str, object] = {"role": role, "content": content}
        if role == "assistant" and tool_calls is not None:
            message_dict["tool_calls"] = tool_calls
        if role == "tool" and tool_call_id is not None:
            message_dict["tool_call_id"] = tool_call_id
        self.messages.append(cast(Message, message_dict))
