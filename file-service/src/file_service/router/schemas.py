from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"


class FileStoreUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1)
    mime: str | None = Field(default=None, min_length=1)
    kind: str | None = Field(default=None, min_length=1)


class FileMetadataData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: str
    name: str
    mime: str
    size: int
    sha256: str


class FileMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: FileMetadataData


class FileTextData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_key: str
    text: str
    truncated: bool


class FileTextResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: FileTextData
