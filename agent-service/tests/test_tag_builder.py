from agent_service.router.schemas import ChatMessage
from agent_service.services.tag_builder import build_session_start_tag, render_messages_xml


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

    assert xml.startswith('<messages mode="start"><message user_id="qq_1" event_time="1710000000">')
    assert xml.count("<message ") == 2
    assert xml.index('user_id="qq_1"') < xml.index('user_id="qq_2"')
    assert ">hello</message>" in xml
    assert ">world</message>" in xml
    assert xml.endswith("</messages>")


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

    assert xml.startswith('<messages mode="start">')
    assert 'user_id="qq_&quot;1"' in xml
    assert ">x &lt; y &amp; \"z\"</message>" in xml
    assert xml.endswith("</messages>")


def test_render_messages_xml_uses_append_mode_wrapper() -> None:
    xml = render_messages_xml(
        messages=[
            ChatMessage(
                user_id="qq_1",
                content="again",
                event_time="1710000001",
            )
        ],
        message_mode="append",
    )

    assert xml == '<messages mode="append"><message user_id="qq_1" event_time="1710000001">again</message></messages>'


def test_build_session_start_tag_with_session_id() -> None:
    tag = build_session_start_tag(
        agent_id='agent_"1',
        metadata={"session_id": 'private_"1'},
    )
    assert tag == '<session_start agent_id="agent_&quot;1" session_id="private_&quot;1">'


def test_build_session_start_tag_without_session_id() -> None:
    tag = build_session_start_tag(agent_id="agent_1", metadata={})
    assert tag == '<session_start agent_id="agent_1">'
