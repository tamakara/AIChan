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
    "reply": ("id",),
    "at": ("qq",),
    "mface": ("emoji_package_id", "emoji_id", "summary"),
    "share": ("url", "title", "content", "image"),
    "location": ("lat", "lon", "title", "content"),
    "contact": ("type", "id"),
}

# NapCat 上报的普通 QQ face 只有 id，没有 name。这里维护接入层最小语义表，
# 让 agent 只看到“表情真意”，避免把 QQ 内部数字 ID 泄漏进对话语义层。
QQ_FACE_NAMES: dict[str, str] = {
    "14": "微笑",
    "1": "撇嘴",
    "2": "色",
    "3": "发呆",
    "4": "得意",
    "5": "流泪",
    "6": "害羞",
    "7": "闭嘴",
    "8": "睡",
    "9": "大哭",
    "10": "尴尬",
    "11": "发怒",
    "12": "调皮",
    "13": "呲牙",
    "15": "难过",
    "49": "拥抱",
    "53": "蛋糕",
    "55": "炸弹",
    "59": "便便",
    "60": "咖啡",
    "63": "玫瑰",
    "64": "凋谢",
    "66": "爱心",
    "67": "心碎",
    "74": "太阳",
    "75": "月亮",
    "76": "赞",
    "77": "踩",
    "78": "握手",
    "79": "胜利",
    "112": "菜刀",
    "114": "篮球",
    "116": "示爱",
    "118": "抱拳",
    "119": "勾引",
    "120": "拳头",
    "121": "差劲",
    "123": "NO",
    "124": "OK",
    "201": "点赞",
    "273": "我酸了",
    "307": "喵喵",
    "311": "打call",
    "314": "仔细分析",
    "318": "崇拜",
    "319": "比心",
    "320": "庆祝",
    "326": "生气",
    "352": "咦",
    "355": "耶",
    "356": "666",
    "357": "裂开",
    "358": "骰子",
    "359": "包剪锤",
}
QQ_FACE_IDS_BY_NAME: dict[str, str] = {name: face_id for face_id, name in QQ_FACE_NAMES.items()}

MEDIA_SEGMENT_TYPES = {"image", "file", "record", "video"}
MEDIA_SEGMENT_ATTRS = ("object_key", "name", "mime", "size", "sha256")
UNSUPPORTED_FILE_ATTRS = ("name", "size", "mime")

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
    target_user_id: int | None = None
    at: bool = False


@dataclass(frozen=True)
class ReplyFileUpload:
    file: str
    name: str
    target_user_id: int | None = None


ReplyOutboundItem = ReplyOnebotMessage | ReplyFileUpload


async def onebot_events_to_input_xml(
    events: list[dict[str, Any]],
    media_storage: InputMediaStorageProtocol | None = None,
    file_resolver: FileUrlResolverProtocol | None = None,
) -> str:
    """把 OneBot11 事件压缩成 agent 可读 XML。

    会话类型等窗口级信息放在 session metadata；每条消息只携带发言人身份。
    群聊里 nickname 可能重复或变化，因此 user_id 必须始终保留给 agent 判断身份边界。
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
    for message in _reply_message_nodes(root):
        for child in list(message.node):
            segments.extend(await _reply_child_to_onebot_segments(child, media_storage))
    return segments


async def reply_xml_to_file_uploads(
    xml: str,
    media_storage: ReplyMediaStorageProtocol | None = None,
) -> list[ReplyFileUpload]:
    root = _reply_root(xml)

    uploads: list[ReplyFileUpload] = []
    for message in _reply_message_nodes(root):
        for child in list(message.node):
            if child.tag != "file":
                continue
            upload = await _reply_file_to_upload(child, media_storage, target_user_id=message.target_user_id)
            if upload is not None:
                uploads.append(upload)
    return uploads


async def reply_xml_to_outbound_items(
    xml: str,
    media_storage: ReplyMediaStorageProtocol | None = None,
) -> list[ReplyOutboundItem]:
    root = _reply_root(xml)

    items: list[ReplyOutboundItem] = []
    for message in _reply_message_nodes(root):
        pending_segments: list[dict[str, Any]] = []
        group_segments = message.node.tag == "message"

        def flush_pending_segments() -> None:
            if not pending_segments:
                return
            items.append(
                ReplyOnebotMessage(
                    message=list(pending_segments),
                    target_user_id=message.target_user_id,
                    at=message.at,
                )
            )
            pending_segments.clear()

        for child in list(message.node):
            if child.tag == "file":
                flush_pending_segments()
                upload = await _reply_file_to_upload(child, media_storage, target_user_id=message.target_user_id)
                if upload is not None:
                    items.append(upload)
                continue

            segments = await _reply_child_to_onebot_segments(child, media_storage)
            if segments:
                if group_segments:
                    # <message> 是协议里的发送原子：同一条回复里的文字、表情和媒体必须保持顺序合并。
                    # file 走 NapCat 上传动作，不是 OneBot message segment，所以在文件前先发送已累计片段。
                    pending_segments.extend(segments)
                    continue

                items.append(
                    ReplyOnebotMessage(
                        message=segments,
                        target_user_id=message.target_user_id,
                        at=message.at,
                    )
                )

        flush_pending_segments()
    return items


def _message_attrs(event: dict[str, Any]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    _set_attr(attrs, "id", event.get("message_id"))
    _set_attr(attrs, "time", event.get("time"))
    _set_attr(attrs, "sub_type", event.get("sub_type"))
    _set_attr(attrs, "user_id", event.get("user_id"))

    sender = event.get("sender")
    if isinstance(sender, dict):
        _set_attr(attrs, "nickname", sender.get("card") or sender.get("nickname"))
    if event.get("message_type") == "group":
        attrs["at_bot"] = "true" if _is_at_bot(event) else "false"
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

    if segment_type == "face":
        _append_face(parent, data)
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


async def _reply_child_to_onebot_segments(
    child: ElementTree.Element,
    media_storage: ReplyMediaStorageProtocol | None,
) -> list[dict[str, Any]]:
    if child.tag == "text":
        return _output_text_segments(child)

    if child.tag == "face":
        data = _output_face_attrs(child)
        if not data:
            return []
        return [_onebot_segment("face", data)]

    if child.tag in OUTPUT_MEDIA_SEGMENT_TYPES:
        data = await _output_media_attrs(child, media_storage)
        if not data:
            return []
        return [_onebot_segment(child.tag, data)]

    return []


async def _reply_file_to_upload(
    child: ElementTree.Element,
    media_storage: ReplyMediaStorageProtocol | None,
    *,
    target_user_id: int | None = None,
) -> ReplyFileUpload | None:
    file = child.attrib.get("file")
    if file:
        name = child.attrib.get("name") or _name_from_file_ref(file)
        return ReplyFileUpload(file=file, name=name, target_user_id=target_user_id)

    object_key = child.attrib.get("object_key")
    if not object_key:
        return None
    if media_storage is None:
        raise ValueError("<file> with object_key requires media storage")

    metadata = await media_storage.metadata(object_key)
    content = await media_storage.content(object_key)
    name = child.attrib.get("name") or metadata.name
    return ReplyFileUpload(
        file="base64://" + b64encode(content).decode("ascii"),
        name=name,
        target_user_id=target_user_id,
    )


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

    # 出站媒体由 hub 通过 file-service 取回，agent 只引用 SHA-256 object_key。
    # NapCat/OneBot v11 发送端支持 base64://，因此不需要把文件服务暴露成公网 URL。
    content = await media_storage.content(object_key)
    return {"file": "base64://" + b64encode(content).decode("ascii")}


def _output_face_attrs(child: ElementTree.Element) -> dict[str, str]:
    # 让 agent 按语义选择表情，hub 在 OneBot 边界翻译为 QQ face id。
    # 兼容 <text> 内联和 <message> 直系两种写法，避免模型按协议并列输出时丢失表情。
    name = child.attrib.get("name", "").strip().removeprefix("/")
    face_id = QQ_FACE_IDS_BY_NAME.get(name)
    if not face_id:
        return {}
    return {"id": face_id}


def _output_text_segments(child: ElementTree.Element) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    _append_output_text_segment(segments, child.text)

    for item in list(child):
        if item.tag == "face":
            data = _output_face_attrs(item)
            if data:
                segments.append(_onebot_segment("face", data))
        _append_output_text_segment(segments, item.tail)

    return segments


def _append_output_text_segment(segments: list[dict[str, Any]], text: str | None) -> None:
    if not text:
        return
    segments.append(_onebot_segment("text", {"text": text}))


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


def _append_face(parent: ElementTree.Element, data: dict[str, Any]) -> None:
    face_id = str(data.get("id", ""))
    face_name = QQ_FACE_NAMES.get(face_id)
    if not face_name:
        _append_unsupported(parent, "face")
        return
    ElementTree.SubElement(parent, "face", {"name": face_name})


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


@dataclass(frozen=True)
class _ReplyMessageNode:
    node: ElementTree.Element
    target_user_id: int | None
    at: bool


def _reply_message_nodes(root: ElementTree.Element) -> list[_ReplyMessageNode]:
    grouped = [child for child in list(root) if child.tag == "message"]
    if not grouped:
        return [_ReplyMessageNode(node=root, target_user_id=None, at=False)]

    messages: list[_ReplyMessageNode] = []
    for child in grouped:
        messages.append(
            _ReplyMessageNode(
                node=child,
                target_user_id=_to_int(child.attrib.get("target_user_id")),
                at=_is_true(child.attrib.get("at")),
            )
        )
    return messages


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


def _is_at_bot(event: dict[str, Any]) -> bool:
    self_id = _to_int(event.get("self_id"))
    if self_id is None:
        return False
    for segment in _message_segments(event.get("message")):
        if segment.get("type") != "at":
            continue
        data = segment.get("data")
        if not isinstance(data, dict):
            continue
        if _to_int(data.get("qq")) == self_id:
            return True
    return False


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def _to_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
