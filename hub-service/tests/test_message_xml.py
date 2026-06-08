from hub_service.services.message_xml import (
    onebot_private_events_to_input_xml,
    reply_xml_to_onebot_segments,
)


def test_onebot_private_events_to_input_xml_keeps_only_dialog_fields() -> None:
    xml = onebot_private_events_to_input_xml(
        [
            {
                "post_type": "message",
                "message_type": "private",
                "sub_type": "friend",
                "message_id": 9,
                "user_id": 1,
                "self_id": 10001,
                "time": 1710000000,
                "raw_message": "drop me",
                "font": 1,
                "sender": {"nickname": "小明", "age": 18},
                "message": [
                    {"type": "text", "data": {"text": "1 < 2 & ok"}},
                    {"type": "image", "data": {"file": "a.jpg", "url": "https://x"}},
                    {"type": "face", "data": {"id": "123"}},
                    {"type": "reply", "data": {"id": "8"}},
                    {"type": "shake", "data": {}},
                ],
            }
        ]
    )

    assert xml.startswith("<messages>")
    assert 'id="9"' in xml
    assert 'nickname="小明"' in xml
    assert "<text>1 &lt; 2 &amp; ok</text>" in xml
    assert '<image file="a.jpg" url="https://x"' in xml
    assert '<face id="123"' in xml
    assert '<reply id="8"' in xml
    assert '<unsupported type="shake"' in xml
    assert "user_id" not in xml
    assert "self_id" not in xml
    assert "raw_message" not in xml
    assert "font" not in xml
    assert 'age="' not in xml


def test_reply_xml_to_onebot_segments() -> None:
    segments = reply_xml_to_onebot_segments(
        '<reply><text>ok</text><image file="https://x" /><face id="123" /></reply>'
    )

    assert segments == [
        {"type": "text", "data": {"text": "ok"}},
        {"type": "image", "data": {"file": "https://x"}},
        {"type": "face", "data": {"id": "123"}},
    ]
