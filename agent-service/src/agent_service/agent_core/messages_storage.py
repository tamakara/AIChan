from typing import List, cast

from .types import LlmMessage, ToolCall


class MessagesStorage:
    def __init__(self):
        self._messages: List[LlmMessage] = []

    def add_system_message(self, content: str) -> None:
        self._messages.append({"role": "system", "content": content})

    def add_assistant_message(self, content: str, tool_calls: List[ToolCall]) -> None:
        self._messages.append(
            cast(
                LlmMessage,
                {"role": "assistant", "content": content, "tool_calls": tool_calls},
            )
        )

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_tool_message(self, name: str, content: str, tool_call_id: str) -> None:
        self._messages.append(
            cast(
                LlmMessage,
                {
                    "role": "tool",
                    "name": name,
                    "content": content,
                    "tool_call_id": tool_call_id,
                },
            )
        )

    def get_messages(self) -> List[LlmMessage]:
        return self._messages
