from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str


class FileFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    name: str | None = None
    mime_type: str | None = None
    kind: str | None = None
