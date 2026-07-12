from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class AdapterInvokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class FileFromUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    name: str | None = None
    mime_type: str | None = None
    kind: str | None = None
