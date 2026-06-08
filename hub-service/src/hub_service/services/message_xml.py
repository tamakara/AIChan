from __future__ import annotations

from typing import Protocol
from typing import Any
from xml.etree import ElementTree

from .media_storage import StoredMedia

INPUT_SEGMENT_ATTRS: dict[str, tuple[str, ...]] = {
    "face": ("id",),
    "reply": ("id",),
    "at": ("qq",),
    "share": ("url", "title", "content", "image"),
    "location": ("lat", "lon", "title", "content"),
    "contact": ("type", "id"),
}

MEDIA_SEGMENT_TYPES = {"image", "file", "record", "video"}
MEDIA_SEGMENT_ATTRS = ("object_key", "name", "mime", "size", "sha256")

OUTPUT_SEGMENT_ATTRS: dict[str, tuple[str, ...]] = {
    "image": ("file",),
    "face": ("id",),
    "record": ("file",),
    "video": ("file",),
}


class MediaStorageProtocol(Protocol):
    async def store_segment(
        self,
        *,
        event: dict[str, Any],
        segment_type: str,
        segment_index: int,
        data: dict[str, Any],
    ) -> StoredMedia:
        ...


async def onebot_private_events_to_input_xml(
    events: list[dict[str, Any]],
    media_storage: MediaStorageProtocol | None = None,
) -> str:
    """把 OneBot11 私聊事件压缩成 agent 可读 XML。

    hub 是唯一理解 OneBot11 的 adapter，因此这里只保留“理解对话”需要的字段。
    用户身份等稳定信息放在 session metadata，避免同一会话每条消息重复消耗 token。
    """
    messages = ElementTree.Element("messages")
    for event in events:
        message = ElementTree.SubElement(
            messages,
            "message",
            _message_attrs(event),
        )
        for index, segment in enumerate(_message_segments(event.get("message"))):
            await _append_input_segment(message, event, index, segment, media_storage)
    return ElementTree.tostring(messages, encoding="unicode", short_empty_elements=True)


def reply_xml_to_onebot_segments(xml: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml)
    if root.tag != "reply":
        raise ValueError("reply xml root must be <reply>")

    segments: list[dict[str, Any]] = []
    for child in list(root):
        if child.tag == "text":
            text = child.text or ""
            if text:
                segments.append({"type": "text", "data": {"text": text}})
            continue
        if child.tag in OUTPUT_SEGMENT_ATTRS:
            data = _attrs(child.attrib, OUTPUT_SEGMENT_ATTRS[child.tag])
            if data:
                segments.append({"type": child.tag, "data": data})
    return segments


def _message_attrs(event: dict[str, Any]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    _set_attr(attrs, "id", event.get("message_id"))
    _set_attr(attrs, "time", event.get("time"))
    _set_attr(attrs, "sub_type", event.get("sub_type"))

    sender = event.get("sender")
    if isinstance(sender, dict):
        _set_attr(attrs, "nickname", sender.get("nickname"))
    return attrs


async def _append_input_segment(
    parent: ElementTree.Element,
    event: dict[str, Any],
    segment_index: int,
    segment: dict[str, Any],
    media_storage: MediaStorageProtocol | None,
) -> None:
    segment_type = str(segment.get("type", ""))
    data = segment.get("data")
    if not isinstance(data, dict):
        data = {}

    if segment_type == "text":
        text = data.get("text")
        if text is not None:
            child = ElementTree.SubElement(parent, "text")
            child.text = str(text)
        return

    if segment_type in MEDIA_SEGMENT_TYPES:
        if media_storage is None or not data.get("url"):
            ElementTree.SubElement(parent, "unsupported", {"type": segment_type or "unknown"})
            return
        try:
            stored = await media_storage.store_segment(
                event=event,
                segment_type=segment_type,
                segment_index=segment_index,
                data=data,
            )
        except Exception:
            # 媒体入库失败时仍保留“用户发过媒体”的事实，但不泄漏 NapCat 临时 URL。
            ElementTree.SubElement(parent, "unsupported", {"type": segment_type, "reason": "storage_failed"})
            return
        ElementTree.SubElement(parent, segment_type, _stored_media_attrs(stored))
        return

    if segment_type in INPUT_SEGMENT_ATTRS:
        ElementTree.SubElement(parent, segment_type, _attrs(data, INPUT_SEGMENT_ATTRS[segment_type]))
        return

    # 未覆盖的 OneBot 段不把原始 data 泄漏给 agent，只告知类型用于对话解释。
    ElementTree.SubElement(parent, "unsupported", {"type": segment_type or "unknown"})


def _message_segments(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _attrs(data: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for name in names:
        _set_attr(attrs, name, data.get(name))
    return attrs


def _stored_media_attrs(stored: StoredMedia) -> dict[str, str]:
    return {
        "object_key": stored.object_key,
        "name": stored.name,
        "mime": stored.mime,
        "size": str(stored.size),
        "sha256": stored.sha256,
    }


def _set_attr(attrs: dict[str, str], name: str, value: object) -> None:
    if value is None:
        return
    attrs[name] = str(value)
