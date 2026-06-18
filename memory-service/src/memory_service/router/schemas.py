from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class MemoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    content_markdown: str


class UserMemoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    content_markdown: str


class CompressMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages_text: str = Field(default="")


class CompressMemoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    content_markdown: str
    added_markdown: str
    added_count: int
