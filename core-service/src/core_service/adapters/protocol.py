from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import quote, urlparse
from uuid import uuid4

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROTOCOL_VERSION = "2.0"
TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
XML_ARGUMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
SCALAR_TYPES = {"string", "integer", "number", "boolean"}
RESERVED_ARGUMENTS = {"type", "xmlns"}


class SkillDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: str = Field(min_length=1)
    description: str = ""
    enabled: bool = True
    content: str = Field(min_length=1)


class CapabilityDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @property
    def tool_name(self) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]", "_", self.name)
        return f"adapter__{normalized}"

    @model_validator(mode="after")
    def validate_schemas(self) -> "CapabilityDefinition":
        Draft202012Validator.check_schema(self.input_schema)
        if self.output_schema:
            Draft202012Validator.check_schema(self.output_schema)
        if not TOOL_NAME_RE.fullmatch(self.tool_name):
            raise ValueError(f"capability 无法转换为合法工具名: {self.name}")
        return self


class ExtensionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: str = Field(min_length=3, pattern=r"^[a-z0-9][a-z0-9._-]*\.[a-z0-9][a-z0-9._-]*$")
    directions: list[Literal["input", "output"]] = Field(min_length=1)
    parameters_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}, "additionalProperties": False})

    @model_validator(mode="after")
    def validate_parameter_schema(self) -> "ExtensionDefinition":
        schema = self.parameters_schema
        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object":
            raise ValueError("extension parameters_schema 必须是 object")
        if schema.get("additionalProperties", False) is not False:
            raise ValueError("extension parameters_schema 必须禁止额外属性")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("extension properties 必须是对象")
        for name, definition in properties.items():
            if name in RESERVED_ARGUMENTS or not XML_ARGUMENT_RE.fullmatch(name):
                raise ValueError(f"extension 参数名不能作为 XML 属性: {name}")
            if not isinstance(definition, dict) or definition.get("type") not in SCALAR_TYPES:
                raise ValueError(f"extension 参数只支持标量类型: {name}")
        if not set(schema.get("required", [])).issubset(properties):
            raise ValueError("extension required 包含未声明参数")
        return self


class AdapterRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    adapter_id: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    file_base_url: str = Field(min_length=1)
    config_schema: dict[str, Any] = Field(default_factory=dict)
    config_summary: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[CapabilityDefinition] = Field(default_factory=list)
    extensions: list[ExtensionDefinition] = Field(default_factory=list)
    skills: list[SkillDocument] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_declarations(self) -> "AdapterRegistration":
        parsed = urlparse(self.file_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("file_base_url 必须是无 query/fragment 的 HTTP(S) 地址")
        for values, label in (([x.tool_name for x in self.capabilities], "capability tool"), ([x.type for x in self.extensions], "extension"), ([x.id for x in self.skills], "skill")):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} 声明重复")
        return self


class PublishedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(min_length=1)
    conversation_type: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    bot_id: str | None = None
    messages_xml: str = Field(min_length=1)


class MessageQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    messages_xml: str = Field(min_length=1)
    next_cursor: str | None = None
    has_more: bool


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["2.0"] = PROTOCOL_VERSION
    type: str
    id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def session_id_for(adapter_id: str, instance_id: str, conversation_type: str, conversation_id: str) -> str:
    return ":".join(quote(item, safe="") for item in (adapter_id, instance_id, conversation_type, conversation_id))
