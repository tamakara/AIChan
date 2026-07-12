from pydantic import BaseModel, ConfigDict, Field


class SkillDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: str = Field(min_length=1)
    description: str = ""
    enabled: bool = True
    content: str = Field(min_length=1)


class AdapterSkillSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    skills: list[SkillDocument] = Field(default_factory=list)


class ResolveSkillsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)


class ResolveSkillsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skills: list[SkillDocument]


class HealthResponse(BaseModel):
    status: str = "ok"
