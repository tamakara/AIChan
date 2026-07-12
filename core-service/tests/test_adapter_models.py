import pytest
from pydantic import ValidationError

from core_service.adapters.protocol import AdapterRegistration, CapabilityDefinition, Envelope, ExtensionDefinition


def test_capability_builds_typed_session_tool() -> None:
    capability = CapabilityDefinition(name="user.get", input_schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})
    assert capability.tool_name == "adapter__user_get"


def test_registration_rejects_tool_collision_and_nested_extension() -> None:
    with pytest.raises(ValidationError):
        ExtensionDefinition(type="qq.bad", directions=["output"], parameters_schema={"type": "object", "properties": {"payload": {"type": "object"}}, "additionalProperties": False})
    with pytest.raises(ValidationError, match="重复"):
        AdapterRegistration(adapter_id="qq", instance_id="main", display_name="QQ", capabilities=[CapabilityDefinition(name="user.get"), CapabilityDefinition(name="user_get")])


def test_envelope_rejects_v1() -> None:
    with pytest.raises(ValidationError):
        Envelope(version="1.0", type="heartbeat.ping")
