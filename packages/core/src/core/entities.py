from pydantic import BaseModel


class UserMessage(BaseModel):
    """标准化后的用户消息。"""

    # 用户输入内容。
    content: str


class AIResponse(BaseModel):
    """标准化后的模型响应。"""

    content: str
