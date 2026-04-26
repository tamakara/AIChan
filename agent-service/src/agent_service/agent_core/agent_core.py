import json

from .llm_client import LlmClient
from .messages_storage import MessagesStorage
from .tool_registry import ToolRegistry


class AgentCore:
    """
    智能体类，负责维护对话历史、管理工具调用流程与大模型交互。
    """

    def __init__(
        self,
        llm_model_name: str,
        llm_api_key: str,
        llm_base_url: str,
        system_prompt: str,
        mcp_gateway_sse_url: str,
        mcp_gateway_auth_token: str = "",
    ):
        self._llm_client = LlmClient(
            model=llm_model_name, api_key=llm_api_key, base_url=llm_base_url
        )

        self._system_prompt = system_prompt
        self._messages_storage = MessagesStorage()
        self._messages_storage.add_system_message(self._system_prompt)

        self._tool_registry = ToolRegistry(
            sse_url=mcp_gateway_sse_url,
            bearer_token=mcp_gateway_auth_token or None,
        )
        self._tool_registry.register_mcp_server()

    def chat(self, user_input: str, max_turns: int = 10) -> str:
        self._messages_storage.add_user_message(user_input)

        # 使用有限轮次循环驱动「模型回复 -> 工具调用 -> 回填结果」闭环，
        # 防止模型持续请求工具导致无界执行。
        for _ in range(max_turns):
            llm_response = self._llm_client.generate(
                messages=self._messages_storage.get_messages(),
                tools_schema=self._tool_registry.get_tools_schema(),
            )
            self._messages_storage.add_assistant_message(
                llm_response.content, llm_response.tool_calls
            )

            if llm_response.finish_reason != "tool_calls":
                if llm_response.finish_reason == "stop":
                    return llm_response.content
                raise RuntimeError(
                    f"LLM response ended with unexpected reason: {llm_response.finish_reason}"
                )

            # 只有模型明确请求工具时才进入调用分支，保持消息流与 OpenAI tool-calls 协议一致。
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
                    tool_call_result = self._tool_registry.call_tool(
                        tool_name=tool_name, tool_args=tool_args
                    )
                except Exception as e:
                    # 即使工具执行失败，也必须回填一条 tool 消息给对应的 tool_call_id。
                    # 这样下一轮请求仍满足 OpenAI 的 tool-calls 协议，避免会话因缺失配对消息而报错中断。
                    tool_call_result = json.dumps(
                        {"error": f"tool `{tool_name}` failed: {e}"},
                        ensure_ascii=False,
                    )

                self._messages_storage.add_tool_message(
                    tool_name, tool_call_result, tool_call_id
                )

        raise RuntimeError(
            f"Agent failed to complete the task within {max_turns} turns of interaction."
        )
