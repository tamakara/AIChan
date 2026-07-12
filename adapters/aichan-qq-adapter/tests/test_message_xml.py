import pytest

from aichan_qq_adapter.message_xml import OutboundPoke, event_to_xml, reply_to_items


class Media:
    async def store_url(self, url, name, mime_type, kind):
        return {"object_key": "abc", "name": name or "x", "mime": mime_type or "image/png"}

    async def base64_file(self, object_key):
        return "base64://eA=="

    async def metadata(self, object_key):
        return {"name": "x.txt"}


class Napcat:
    async def action(self, action, params):
        return {}


@pytest.mark.asyncio
async def test_face_and_identity_are_channel_extensions() -> None:
    xml = await event_to_xml({
        "post_type": "message", "message_id": 1, "time": 2, "user_id": 3, "self_id": 4,
        "sender": {"nickname": "n"}, "message": [{"type": "face", "data": {"id": "14"}}],
    }, Media(), Napcat())
    assert 'sender_id="3"' in xml
    assert 'namespace="qq" name="face"' in xml


@pytest.mark.asyncio
async def test_poke_output_is_extension_action() -> None:
    items = await reply_to_items(
        '<reply><message><extension namespace="qq" name="poke"><param name="target_id">3</param></extension></message></reply>',
        Media(),
    )
    assert items == [OutboundPoke("3")]
