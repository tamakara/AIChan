import pytest

from hub_service.services.media_storage import StoredMedia
from hub_service.services.message_xml import (
    onebot_events_to_input_xml,
    ReplyFileUpload,
    ReplyOnebotMessage,
    reply_xml_to_outbound_items,
    reply_xml_to_onebot_segments,
)

OBJECT_KEY = "a" * 64


class StubMediaStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, dict]] = []
        self.contents: dict[str, bytes] = {}

    async def store_segment(self, *, event, segment_type, segment_index, data) -> StoredMedia:
        self.calls.append((segment_type, segment_index, data))
        name = data.get("name") or data.get("file") or f"{segment_type}.bin"
        mime = "image/jpeg" if segment_type == "image" else "text/plain"
        return StoredMedia(
            object_key=OBJECT_KEY,
            name=name,
            mime=mime,
            size=123,
            sha256=OBJECT_KEY,
        )

    async def content(self, object_key: str) -> bytes:
        return self.contents[object_key]

    async def metadata(self, object_key: str) -> StoredMedia:
        return StoredMedia(
            object_key=object_key,
            name=object_key.rsplit("/", 1)[-1],
            mime="application/octet-stream",
            size=len(self.contents[object_key]),
            sha256=object_key,
        )


class StubFileResolver:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.calls: list[tuple[dict, dict]] = []

    async def resolve_file_url(self, *, event, data) -> str | None:
        self.calls.append((event, data))
        return self.url


@pytest.mark.asyncio
async def test_onebot_events_to_input_xml_keeps_dialog_fields() -> None:
    storage = StubMediaStorage()
    xml = await onebot_events_to_input_xml(
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
    assert 'user_id="1"' in xml
    assert 'nickname="小明"' in xml
    assert "<text>1 &lt; 2 &amp; ok</text>" in xml
    assert f'<image object_key="{OBJECT_KEY}" name="a.jpg" mime="image/jpeg" size="123" sha256="{OBJECT_KEY}"' in xml
    assert "https://x" not in xml
    assert '<face id="123"' in xml
    assert '<reply id="8"' in xml
    assert '<unsupported type="shake"' in xml
    assert "self_id" not in xml
    assert "raw_message" not in xml
    assert "font" not in xml
    assert 'age="' not in xml


@pytest.mark.asyncio
async def test_onebot_group_event_marks_sender_and_at_bot() -> None:
    xml = await onebot_events_to_input_xml(
        [
            {
                "post_type": "message",
                "message_type": "group",
                "sub_type": "normal",
                "message_id": 9,
                "group_id": 20001,
                "user_id": 1,
                "self_id": 10001,
                "time": 1710000000,
                "sender": {"nickname": "昵称", "card": "群名片"},
                "message": [
                    {"type": "at", "data": {"qq": "10001"}},
                    {"type": "text", "data": {"text": "hello"}},
                ],
            }
        ],
    )

    assert 'user_id="1"' in xml
    assert 'nickname="群名片"' in xml
    assert 'at_bot="true"' in xml
    assert '<at qq="10001"' in xml


@pytest.mark.asyncio
async def test_file_segment_with_url_is_stored() -> None:
    xml = await onebot_events_to_input_xml(
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

    assert f'<file object_key="{OBJECT_KEY}" name="a.txt" mime="text/plain" size="123" sha256="{OBJECT_KEY}"' in xml
    assert "https://file" not in xml


@pytest.mark.asyncio
async def test_file_segment_without_url_is_unsupported() -> None:
    xml = await onebot_events_to_input_xml(
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
    assert 'name="a.txt"' in xml


@pytest.mark.asyncio
async def test_file_segment_without_url_uses_resolver() -> None:
    storage = StubMediaStorage()
    resolver = StubFileResolver(url="https://resolved-file")

    xml = await onebot_events_to_input_xml(
        [
            {
                "message_id": 10,
                "user_id": 1,
                "message": [{"type": "file", "data": {"name": "a.txt", "file_id": "file-1"}}],
            }
        ],
        media_storage=storage,
        file_resolver=resolver,
    )

    assert f'<file object_key="{OBJECT_KEY}" name="a.txt" mime="text/plain" size="123" sha256="{OBJECT_KEY}"' in xml
    assert resolver.calls[0][1] == {"name": "a.txt", "file_id": "file-1"}
    assert storage.calls[0][2]["url"] == "https://resolved-file"
    assert "https://resolved-file" not in xml


@pytest.mark.asyncio
async def test_reply_xml_to_onebot_segments() -> None:
    segments = await reply_xml_to_onebot_segments(
        '<reply><text>ok</text><image file="https://x" /><face id="123" /></reply>'
    )

    assert segments == [
        {"type": "text", "data": {"text": "ok"}},
        {"type": "image", "data": {"file": "https://x"}},
        {"type": "face", "data": {"id": "123"}},
    ]


@pytest.mark.asyncio
async def test_reply_xml_to_onebot_segments_loads_image_from_storage() -> None:
    storage = StubMediaStorage()
    storage.contents[OBJECT_KEY] = b"image-bytes"

    segments = await reply_xml_to_onebot_segments(
        f'<reply><image object_key="{OBJECT_KEY}" /></reply>',
        media_storage=storage,
    )

    assert segments == [
        {"type": "image", "data": {"file": "base64://aW1hZ2UtYnl0ZXM="}},
    ]


@pytest.mark.asyncio
async def test_reply_xml_to_outbound_items_splits_direct_children_in_order() -> None:
    storage = StubMediaStorage()
    image_key = "a" * 64
    file_key = "b" * 64
    storage.contents[image_key] = b"image-bytes"
    storage.contents[file_key] = b"note"

    items = await reply_xml_to_outbound_items(
        (
            f'<reply><text>first</text><image object_key="{image_key}" />'
            f'<text>second</text><file object_key="{file_key}" /></reply>'
        ),
        media_storage=storage,
    )

    assert items == [
        ReplyOnebotMessage(message=[{"type": "text", "data": {"text": "first"}}]),
        ReplyOnebotMessage(message=[{"type": "image", "data": {"file": "base64://aW1hZ2UtYnl0ZXM="}}]),
        ReplyOnebotMessage(message=[{"type": "text", "data": {"text": "second"}}]),
        ReplyFileUpload(file="base64://bm90ZQ==", name=file_key),
    ]


@pytest.mark.asyncio
async def test_reply_xml_to_outbound_items_keeps_group_reply_target() -> None:
    items = await reply_xml_to_outbound_items(
        '<reply><message target_user_id="2" target_nickname="小红" at="true">'
        '<text>收到喵</text></message></reply>'
    )

    assert items == [
        ReplyOnebotMessage(
            message=[{"type": "text", "data": {"text": "收到喵"}}],
            target_user_id=2,
            at=True,
        )
    ]
