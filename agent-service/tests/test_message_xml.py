from agent_service.router.schemas import ChatMessage
from agent_service.services.message_xml import render_messages_xml


def test_render_messages_xml_preserves_order_and_fields() -> None:
    xml = render_messages_xml(
        metadata={"session_id": "private_1"},
        messages=[
            ChatMessage(
                user_id="qq_1",
                content="hello",
                event_time="1710000000",
            ),
            ChatMessage(
                user_id="qq_2",
                content="world",
                event_time="1710000001",
            ),
        ],
    )

    assert xml.startswith('<chat_messages session_id="private_1">')
    assert xml.count("<message ") == 2
    assert xml.index('user_id="qq_1"') < xml.index('user_id="qq_2"')
    assert ">hello</message>" in xml
    assert ">world</message>" in xml
    assert xml.endswith("</chat_messages>")


def test_render_messages_xml_escapes_attr_and_text() -> None:
    xml = render_messages_xml(
        metadata={'session_id': 'private_"1"', 'x"y': 'v"z'},
        messages=[
            ChatMessage(
                user_id='qq_"1',
                content='x < y & "z"',
                event_time="1710000000",
            )
        ],
    )

    assert 'session_id="private_&quot;1&quot;"' in xml
    assert 'x&quot;y="v&quot;z"' in xml
    assert 'user_id="qq_&quot;1"' in xml
    assert ">x &lt; y &amp; \"z\"</message>" in xml
