import json
from pathlib import Path

import pytest
from jsonschema import validate

from core_service.adapters.protocol import AdapterRegistration, ExtensionDefinition
from core_service.adapters.xml_codec import XmlMessageCodec

KEY = "a" * 64


def registration() -> AdapterRegistration:
    return AdapterRegistration(
        adapter_id="qq",
        instance_id="main",
        display_name="QQ",
        extensions=[ExtensionDefinition(
            type="qq.poke",
            directions=["output"],
            parameters_schema={
                "type": "object",
                "properties": {"target_id": {"type": "string"}, "count": {"type": "integer"}},
                "required": ["target_id"],
                "additionalProperties": False,
            },
        )],
    )


def test_xml_v2_validates_and_normalizes_messages_and_reply() -> None:
    codec = XmlMessageCodec()
    messages = codec.validate_messages(
        f'<messages><message id="1" timestamp="1710000000" sender_id="u1"><text>hi</text><image object_key="{KEY}" /></message></messages>',
        registration(),
    )
    assert messages.object_keys == {KEY}
    reply = codec.validate_reply(
        '<reply><message target_id="u1"><text>ok</text><extension type="qq.poke" target_id="u1" count="2" /></message></reply>',
        registration(),
        {KEY},
    )
    assert reply.xml.startswith("<reply>")


def test_xml_v2_rejects_unsafe_or_untrusted_content() -> None:
    codec = XmlMessageCodec()
    with pytest.raises(ValueError, match="DTD"):
        codec.validate_messages('<!DOCTYPE x><messages />', registration())
    with pytest.raises(ValueError, match="未知 object_key"):
        codec.validate_reply(f'<reply><message><image object_key="{KEY}" /></message></reply>', registration(), set())
    with pytest.raises(ValueError, match="无法转换"):
        codec.validate_reply('<reply><message><extension type="qq.poke" target_id="u1" count="many" /></message></reply>', registration(), set())


def test_protocol_v2_golden_registration_matches_schema() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "protocol/adapter/v2/envelope.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "protocol/adapter/v2/examples/register.json").read_text(encoding="utf-8"))
    validate(example, schema)
