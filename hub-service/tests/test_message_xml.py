import pytest

from hub_service.services.media_storage import StoredMedia
from hub_service.services.message_xml import (
    onebot_private_events_to_input_xml,
    reply_xml_to_onebot_segments,
)


class StubMediaStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []

    async def store_segment(self, *, event, segment_type, segment_index, data) -> StoredMedia:
        self.calls.append((segment_type, segment_index, data))
        name = data.get("name") or data.get("file") or f"{segment_type}.bin"
        mime = "image/jpeg" if segment_type == "image" else "text/plain"
        return StoredMedia(
            object_key=f"qq/private/{event['user_id']}/{event['message_id']}/{segment_index}-abc.txt",
            name=name,
            mime=mime,
            size=123,
            sha256="abc",
        )


@pytest.mark.asyncio
async def test_onebot_private_events_to_input_xml_keeps_only_dialog_fields() -> None:
    storage = StubMediaStorage()
    xml = await onebot_private_events_to_input_xml(
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
        ],
        media_storage=storage,
    )

    assert xml.startswith("<messages>")
    assert 'id="9"' in xml
    assert 'nickname="小明"' in xml
    assert "<text>1 &lt; 2 &amp; ok</text>" in xml
    assert '<image object_key="qq/private/1/9/1-abc.txt" name="a.jpg" mime="image/jpeg" size="123" sha256="abc"' in xml
    assert "https://x" not in xml
    assert '<face id="123"' in xml
    assert '<reply id="8"' in xml
    assert '<unsupported type="shake"' in xml
    assert "user_id" not in xml
    assert "self_id" not in xml
    assert "raw_message" not in xml
    assert "font" not in xml
    assert 'age="' not in xml


@pytest.mark.asyncio
async def test_file_segment_with_url_is_stored() -> None:
    xml = await onebot_private_events_to_input_xml(
        [
            {
                "message_id": 10,
                "user_id": 1,
                "message": [
                    {"type": "file", "data": {"name": "a.txt", "url": "https://file"}},
                ],
            }
        ],
        media_storage=StubMediaStorage(),
    )

    assert '<file object_key="qq/private/1/10/0-abc.txt" name="a.txt" mime="text/plain" size="123" sha256="abc"' in xml
    assert "https://file" not in xml


@pytest.mark.asyncio
async def test_file_segment_without_url_is_unsupported() -> None:
    xml = await onebot_private_events_to_input_xml(
        [
            {
                "message_id": 10,
                "user_id": 1,
                "message": [{"type": "file", "data": {"name": "a.txt"}}],
            }
        ],
        media_storage=StubMediaStorage(),
    )

    assert '<unsupported type="file"' in xml
    assert "a.txt" not in xml


def test_reply_xml_to_onebot_segments() -> None:
    segments = reply_xml_to_onebot_segments(
        '<reply><text>ok</text><image file="https://x" /><face id="123" /></reply>'
    )

    assert segments == [
        {"type": "text", "data": {"text": "ok"}},
        {"type": "image", "data": {"file": "https://x"}},
        {"type": "face", "data": {"id": "123"}},
    ]
