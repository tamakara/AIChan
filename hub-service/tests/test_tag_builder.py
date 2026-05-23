from hub_service.services.tag_builder import build_batch_xml


def test_build_batch_xml_keeps_event_order_and_tags() -> None:
    batch_xml = build_batch_xml(
        event_xmls=[
            '<message message_type="private" sub_type="friend" message_id="11" '
            'session_id="private_1" user_id="qq_1" time="1710000000">hello</message>',
            '<poke session_id="private_1" user_id="qq_1" target_id="qq_2" />',
            '<recall session_id="private_1" user_id="qq_1" message_id="10" />',
        ],
        batch_type="append",
    )
    assert (
        batch_xml
        == '<batch type="append"><message message_type="private" sub_type="friend" message_id="11" '
        'session_id="private_1" user_id="qq_1" time="1710000000">hello</message>'
        '<poke session_id="private_1" user_id="qq_1" target_id="qq_2" />'
        '<recall session_id="private_1" user_id="qq_1" message_id="10" /></batch>'
    )


def test_build_batch_xml_trims_event_xml_edges() -> None:
    batch_xml = build_batch_xml(
        event_xmls=[
            "  <message message_type=\"private\" sub_type=\"friend\" message_id=\"11\" "
            "session_id=\"private_1\" user_id=\"qq_1\" time=\"1710000000\">hello</message>\n",
        ],
        batch_type="start",
    )
    assert (
        batch_xml
        == '<batch type="start"><message message_type="private" sub_type="friend" '
        'message_id="11" session_id="private_1" user_id="qq_1" '
        'time="1710000000">hello</message></batch>'
    )
