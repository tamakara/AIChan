from agent_service.router.schemas import ChatMessage
from agent_service.services.message_xml import render_messages_xml


def test_render_messages_xml_preserves_order_and_fields() -> None:
    xml = render_messages_xml(
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

    assert xml.startswith('<message user_id="qq_1" event_time="1710000000">')
    assert xml.count("<message ") == 2
    assert xml.index('user_id="qq_1"') < xml.index('user_id="qq_2"')
    assert ">hello</message>" in xml
    assert ">world</message>" in xml
    assert "<chat_messages" not in xml


def test_render_messages_xml_escapes_attr_and_text() -> None:
    xml = render_messages_xml(
        messages=[
            ChatMessage(
                user_id='qq_"1',
                content='x < y & "z"',
                event_time="1710000000",
            )
        ],
    )

    assert 'user_id="qq_&quot;1"' in xml
    assert ">x &lt; y &amp; \"z\"</message>" in xml
