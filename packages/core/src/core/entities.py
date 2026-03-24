from typing import Literal

from pydantic import BaseModel, Field


class UserMessage(BaseModel):
    """标准化后的用户消息。"""

    # 用户输入内容。
    content: str


class AIResponse(BaseModel):
    """标准化后的模型响应。"""

    content: str


class ChannelMessage(BaseModel):
    """通道内存储的标准消息结构。"""

    message_id: int = Field(..., ge=1, description="通道内递增消息 ID")
    channel: str = Field(..., description="消息所属通道名称")
    role: Literal["user", "assistant", "system"] = Field(..., description="消息角色")
    content: str = Field(..., description="消息文本")


class AgentSignal(BaseModel):
    """主程序发送给 Agent 的处理信号。"""

    channel: str = Field(..., description="触发处理的通道名称")
