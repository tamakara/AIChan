import pytest
import json
from pathlib import Path

from jsonschema import validate
from hub_service.services.adapter_registry import _validate_xml
from hub_service.services.protocol import AdapterRegistration, Envelope, ExtensionDefinition, session_id_for


def test_session_id_is_stable_and_channel_scoped() -> None:
    assert session_id_for("qq", "main", "group", "1/2") == "qq:main:group:1%2F2"
    assert session_id_for("other", "main", "group", "1/2") != session_id_for("qq", "main", "group", "1/2")


def test_envelope_uses_protocol_v1() -> None:
    envelope = Envelope(type="heartbeat.ping")
    assert envelope.version == "1.0"
    assert envelope.id


def test_xml_rejects_undeclared_channel_extension() -> None:
    registration = AdapterRegistration(
        adapter_id="qq", instance_id="main", display_name="QQ",
        extensions=[ExtensionDefinition(
            namespace="qq", name="poke", directions=["output"],
            parameters_schema={"type": "object", "required": ["target_id"]},
        )],
    )
    _validate_xml(
        '<reply><message><extension namespace="qq" name="poke"><param name="target_id">1</param></extension></message></reply>',
        registration, "output",
    )
    with pytest.raises(ValueError, match="not declared"):
        _validate_xml(
            '<reply><message><extension namespace="qq" name="unknown" /></message></reply>',
            registration, "output",
        )


def test_golden_registration_matches_shared_envelope_schema() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "protocol/adapter/v1/envelope.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "protocol/adapter/v1/examples/register.json").read_text(encoding="utf-8"))
    validate(example, schema)
