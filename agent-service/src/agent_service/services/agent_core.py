import json

from .llm_client import LlmClient
from .mcp_gateway import McpGateway
from .types.context import Context


class AgentCore:
    def __init__(
        self,
        llm_client: LlmClient,
        mcp_gateway: McpGateway,
        max_turns: int,
        temperature: float,
    ):
        self._llm_client = llm_client
        self._mcp_gateway = mcp_gateway
        self._max_turns = max_turns
        self._temperature = temperature

    @property
    def max_turns(self) -> int:
        return self._max_turns

    def run(self, context: Context) -> str:
        for _ in range(self._max_turns):
            llm_response = self._llm_client.generate(
                messages=context.messages,
                tools_schema=self._mcp_gateway.get_tools_schema(),
                temperature=self._temperature,
            )
            context.add_message(
                role="assistant",
                content=llm_response.content,
                tool_calls=llm_response.tool_calls,
            )
            if llm_response.finish_reason != "tool_calls":
                if llm_response.finish_reason == "stop":
                    return llm_response.content
                raise RuntimeError(
                    f"LLM response ended with unexpected reason: {llm_response.finish_reason}"
                )

            for tool_call in llm_response.tool_calls:
                tool_call_id = tool_call.id
                tool_name = tool_call.function.name
                tool_args_str = tool_call.function.arguments

                try:
                    tool_args = (
                        json.loads(tool_args_str)
                        if isinstance(tool_args_str, str)
                        else tool_args_str
                    )
                    tool_call_result = self._mcp_gateway.call_tool(
                        tool_name=tool_name, tool_args=tool_args
                    )
                except Exception as e:
                    tool_call_result = json.dumps(
                        {"error": f"tool `{tool_name}` failed: {e}"},
                        ensure_ascii=False,
                    )

                context.add_message(
                    role="tool",
                    content=tool_call_result,
                    tool_call_id=tool_call_id,
                )

        raise RuntimeError(
            f"Agent failed to complete the task within {self._max_turns} turns of interaction."
        )
