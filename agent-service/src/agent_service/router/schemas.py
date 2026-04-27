from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_input: str = Field(min_length=1)
    max_turns: int = Field(default=10, ge=1, le=50)


class ChatResponse(BaseModel):
    reply: str


class HealthResponse(BaseModel):
    status: str
