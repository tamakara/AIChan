from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from typing import Any
from urllib.parse import unquote, urlparse
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
UNSUPPORTED_FILE_ATTRS = ("name", "size", "mime")

OUTPUT_SEGMENT_ATTRS: dict[str, tuple[str, ...]] = {
    "face": ("id",),
}
OUTPUT_MEDIA_SEGMENT_TYPES = {"image", "record", "video"}


class InputMediaStorageProtocol(Protocol):
    async def store_segment(
        self,
        *,
        event: dict[str, Any],
        segment_type: str,
        segment_index: int,
        data: dict[str, Any],
    ) -> StoredMedia:
        ...


class FileUrlResolverProtocol(Protocol):
    async def resolve_file_url(
        self,
        *,
        event: dict[str, Any],
        data: dict[str, Any],
    ) -> str | None:
        ...


class ReplyMediaStorageProtocol(Protocol):
    async def metadata(self, object_key: str) -> StoredMedia:
        ...

    async def content(self, object_key: str) -> bytes:
        ...


@dataclass(frozen=True)
class ReplyOnebotMessage:
    message: list[dict[str, Any]]


@dataclass(frozen=True)
class ReplyFileUpload:
    file: str
    name: str


ReplyOutboundItem = ReplyOnebotMessage | ReplyFileUpload


async def onebot_private_events_to_input_xml(
    events: list[dict[str, Any]],
    media_storage: InputMediaStorageProtocol | None = None,
    file_resolver: FileUrlResolverProtocol | None = None,
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
            await _append_input_segment(message, event, index, segment, media_storage, file_resolver)
    return ElementTree.tostring(messages, encoding="unicode", short_empty_elements=True)


async def reply_xml_to_onebot_segments(
    xml: str,
    media_storage: ReplyMediaStorageProtocol | None = None,
) -> list[dict[str, Any]]:
    root = _reply_root(xml)

    segments: list[dict[str, Any]] = []
    for child in list(root):
        segment = await _reply_child_to_onebot_segment(child, media_storage)
        if segment is not None:
            segments.append(segment)
    return segments


async def reply_xml_to_file_uploads(
    xml: str,
    media_storage: ReplyMediaStorageProtocol | None = None,
) -> list[ReplyFileUpload]:
    root = _reply_root(xml)

    uploads: list[ReplyFileUpload] = []
    for child in list(root):
        if child.tag != "file":
            continue
        upload = await _reply_file_to_upload(child, media_storage)
        if upload is not None:
            uploads.append(upload)
    return uploads


async def reply_xml_to_outbound_items(
    xml: str,
    media_storage: ReplyMediaStorageProtocol | None = None,
) -> list[ReplyOutboundItem]:
    root = _reply_root(xml)

    items: list[ReplyOutboundItem] = []
    for child in list(root):
        if child.tag == "file":
            upload = await _reply_file_to_upload(child, media_storage)
            if upload is not None:
                items.append(upload)
            continue

        segment = await _reply_child_to_onebot_segment(child, media_storage)
        if segment is not None:
            # QQ/NapCat 对图文混排消息的展示并不稳定；这里按 `<reply>` 直系子节点拆分，
            # 让文本、视频、图片等都成为独立动作，保证用户能看到每一段回复。
            items.append(ReplyOnebotMessage(message=[segment]))
    return items


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
    media_storage: InputMediaStorageProtocol | None,
    file_resolver: FileUrlResolverProtocol | None,
) -> None:
    segment_type = str(segment.get("type", ""))
    data = segment.get("data")
    if not isinstance(data, dict):
        data = {}

    if segment_type == "text":
        _append_text(parent, data.get("text"))
        return

    if segment_type in MEDIA_SEGMENT_TYPES:
        await _append_stored_media(
            parent,
            event,
            segment_index,
            segment_type,
            data,
            media_storage,
            file_resolver,
        )
        return

    attr_names = INPUT_SEGMENT_ATTRS.get(segment_type)
    if attr_names is not None:
        _append_attrs(parent, segment_type, data, attr_names)
        return

    # 未覆盖的 OneBot 段不把原始 data 泄漏给 agent，只告知类型用于对话解释。
    _append_unsupported(parent, segment_type)


def _message_segments(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _attrs(data: dict[str, Any], names: tuple[str, ...]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for name in names:
        _set_attr(attrs, name, data.get(name))
    return attrs


async def _reply_child_to_onebot_segment(
    child: ElementTree.Element,
    media_storage: ReplyMediaStorageProtocol | None,
) -> dict[str, Any] | None:
    if child.tag == "text":
        text = child.text or ""
        if not text:
            return None
        return _onebot_segment("text", {"text": text})

    if child.tag in OUTPUT_MEDIA_SEGMENT_TYPES:
        data = await _output_media_attrs(child, media_storage)
        if not data:
            return None
        return _onebot_segment(child.tag, data)

    attr_names = OUTPUT_SEGMENT_ATTRS.get(child.tag)
    if attr_names is None:
        return None

    data = _attrs(child.attrib, attr_names)
    if not data:
        return None
    return _onebot_segment(child.tag, data)


async def _reply_file_to_upload(
    child: ElementTree.Element,
    media_storage: ReplyMediaStorageProtocol | None,
) -> ReplyFileUpload | None:
    file = child.attrib.get("file")
    if file:
        name = child.attrib.get("name") or _name_from_file_ref(file)
        return ReplyFileUpload(file=file, name=name)

    object_key = child.attrib.get("object_key")
    if not object_key:
        return None
    if media_storage is None:
        raise ValueError("<file> with object_key requires media storage")

    metadata = await media_storage.metadata(object_key)
    content = await media_storage.content(object_key)
    name = child.attrib.get("name") or metadata.name
    return ReplyFileUpload(file="base64://" + b64encode(content).decode("ascii"), name=name)


def _onebot_segment(segment_type: str, data: dict[str, str]) -> dict[str, Any]:
    return {"type": segment_type, "data": data}


async def _output_media_attrs(
    child: ElementTree.Element,
    media_storage: ReplyMediaStorageProtocol | None,
) -> dict[str, str]:
    file = child.attrib.get("file")
    if file:
        return {"file": file}

    object_key = child.attrib.get("object_key")
    if not object_key:
        return {}
    if media_storage is None:
        raise ValueError(f"<{child.tag}> with object_key requires media storage")

    # 出站媒体仍由 hub 从私有 MinIO 读取，agent 只引用 object_key。
    # NapCat/OneBot v11 发送端支持 base64://，因此不需要把 MinIO 暴露成公网 URL。
    content = await media_storage.content(object_key)
    return {"file": "base64://" + b64encode(content).decode("ascii")}


async def _append_stored_media(
    parent: ElementTree.Element,
    event: dict[str, Any],
    segment_index: int,
    segment_type: str,
    data: dict[str, Any],
    media_storage: InputMediaStorageProtocol | None,
    file_resolver: FileUrlResolverProtocol | None,
) -> None:
    if media_storage is None:
        _append_unsupported(parent, segment_type, data=data)
        return

    data = await _with_resolved_media_url(segment_type, event, data, file_resolver)
    if not data.get("url"):
        _append_unsupported(parent, segment_type, data=data)
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
        _append_unsupported(parent, segment_type, reason="storage_failed", data=data)
        return

    ElementTree.SubElement(parent, segment_type, _stored_media_attrs(stored))


async def _with_resolved_media_url(
    segment_type: str,
    event: dict[str, Any],
    data: dict[str, Any],
    file_resolver: FileUrlResolverProtocol | None,
) -> dict[str, Any]:
    if data.get("url") or segment_type != "file" or file_resolver is None:
        return data

    resolved_url = await file_resolver.resolve_file_url(event=event, data=data)
    if not resolved_url:
        return data
    return {**data, "url": resolved_url}


def _append_text(parent: ElementTree.Element, text: object) -> None:
    if text is None:
        return
    child = ElementTree.SubElement(parent, "text")
    child.text = str(text)


def _append_attrs(
    parent: ElementTree.Element,
    tag: str,
    data: dict[str, Any],
    attr_names: tuple[str, ...],
) -> None:
    ElementTree.SubElement(parent, tag, _attrs(data, attr_names))


def _append_unsupported(
    parent: ElementTree.Element,
    segment_type: str,
    *,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    attrs = {"type": segment_type or "unknown"}
    _set_attr(attrs, "reason", reason)
    if segment_type == "file" and data is not None:
        attrs.update(_attrs(data, UNSUPPORTED_FILE_ATTRS))
    ElementTree.SubElement(parent, "unsupported", attrs)


def _stored_media_attrs(stored: StoredMedia) -> dict[str, str]:
    return {
        "object_key": stored.object_key,
        "name": stored.name,
        "mime": stored.mime,
        "size": str(stored.size),
        "sha256": stored.sha256,
    }


def _reply_root(xml: str) -> ElementTree.Element:
    root = ElementTree.fromstring(xml)
    if root.tag != "reply":
        raise ValueError("reply xml root must be <reply>")
    return root


def _name_from_file_ref(file: str) -> str:
    parsed = urlparse(file)
    name = PurePosixPath(unquote(parsed.path)).name
    if name:
        return name
    return "file"


def _set_attr(attrs: dict[str, str], name: str, value: object) -> None:
    if value is None:
        return
    attrs[name] = str(value)
