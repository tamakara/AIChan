import json
from pathlib import Path

import pytest
from jsonschema import validate

from core_service.adapters.protocol import AdapterRegistration, ExtensionDefinition
from core_service.adapters.xml_codec import XmlMessageCodec


def registration() -> AdapterRegistration:
    return AdapterRegistration(
        adapter_id="qq",
        instance_id="main",
        display_name="QQ",
        file_base_url="http://qq-adapter:8080/api/v2/files",
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


def test_xml_v2_uses_only_text_and_file_references() -> None:
    codec = XmlMessageCodec()
    messages = codec.validate_messages(
        '<messages><message id="1" timestamp="1710000000" sender_id="u1"><text>hi</text><file ref="msg:1:file:1" name="a.png" /></message></messages>',
        registration(),
    )
    assert messages.file_refs == {"msg:1:file:1"}
    reply = codec.validate_reply(
        '<reply><message target_id="u1"><text>ok</text><file ref="msg:1:file:1" /><extension type="qq.poke" target_id="u1" count="2" /></message></reply>',
        registration(),
        {"msg:1:file:1"},
    )
    assert reply.file_refs == {"msg:1:file:1"}


def test_xml_v2_rejects_old_media_nodes_and_unknown_refs() -> None:
    codec = XmlMessageCodec()
    with pytest.raises(ValueError, match="不支持节点"):
        codec.validate_messages('<messages><message id="1" timestamp="1" sender_id="u"><image object_key="x" /></message></messages>', registration())
    with pytest.raises(ValueError, match="未知 file ref"):
        codec.validate_reply('<reply><message><file ref="unknown" /></message></reply>', registration(), set())
    with pytest.raises(ValueError, match="未知属性"):
        codec.validate_reply('<reply><message><file ref="x" mime_type="image/png" /></message></reply>', registration(), {"x"})


def test_protocol_v2_golden_registration_matches_schema() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads((root / "protocol/adapter/v2/envelope.schema.json").read_text(encoding="utf-8"))
    example = json.loads((root / "protocol/adapter/v2/examples/register.json").read_text(encoding="utf-8"))
    validate(example, schema)
