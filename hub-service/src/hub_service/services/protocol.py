from __future__ import annotations

from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1.0"


class SkillDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    version: str
    description: str = ""
    enabled: bool = True
    content: str


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ExtensionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    name: str
    directions: list[Literal["input", "output"]]
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class AdapterRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter_id: str
    instance_id: str
    display_name: str
    config_schema: dict[str, Any] = Field(default_factory=dict)
    config_summary: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[CapabilityDefinition] = Field(default_factory=list)
    extensions: list[ExtensionDefinition] = Field(default_factory=list)
    skills: list[SkillDocument] = Field(default_factory=list)


class PublishedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    conversation_type: str
    conversation_id: str
    bot_id: str | None = None
    input_xml: str


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["1.0"] = PROTOCOL_VERSION
    type: str
    id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def session_id_for(adapter_id: str, instance_id: str, conversation_type: str, conversation_id: str) -> str:
    return ":".join(quote(item, safe="") for item in (
        adapter_id, instance_id, conversation_type, conversation_id,
    ))
