from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from .media import HubMediaClient
from .napcat import NapcatGateway, is_at_bot, message_segments

QQ_FACE_NAMES = {
    "14": "微笑", "1": "撇嘴", "2": "色", "3": "发呆", "4": "得意", "5": "流泪",
    "6": "害羞", "7": "闭嘴", "8": "睡", "9": "大哭", "10": "尴尬", "11": "发怒",
    "12": "调皮", "13": "呲牙", "15": "难过", "49": "拥抱", "53": "蛋糕", "55": "炸弹",
    "59": "便便", "60": "咖啡", "63": "玫瑰", "64": "凋谢", "66": "爱心", "67": "心碎",
    "74": "太阳", "75": "月亮", "76": "赞", "77": "踩", "78": "握手", "79": "胜利",
    "112": "菜刀", "114": "篮球", "116": "示爱", "118": "抱拳", "119": "勾引",
    "120": "拳头", "121": "差劲", "123": "NO", "124": "OK", "201": "点赞", "273": "我酸了",
    "307": "喵喵", "311": "打call", "314": "仔细分析", "318": "崇拜", "319": "比心",
    "320": "庆祝", "326": "生气", "352": "咦", "355": "耶", "356": "666", "357": "裂开",
    "358": "骰子", "359": "包剪锤",
}
QQ_FACE_IDS = {name: face_id for face_id, name in QQ_FACE_NAMES.items()}


@dataclass(frozen=True)
class OutboundMessage:
    segments: list[dict[str, Any]]
    target_id: str | None
    mention: bool


@dataclass(frozen=True)
class OutboundFile:
    file: str
    name: str
    target_id: str | None


@dataclass(frozen=True)
class OutboundPoke:
    target_id: str


OutboundItem = OutboundMessage | OutboundFile | OutboundPoke


async def event_to_xml(event: dict[str, Any], media: HubMediaClient, napcat: NapcatGateway) -> str:
    root = ElementTree.Element("messages")
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    attrs = {
        "id": str(event.get("message_id", event.get("time", ""))),
        "timestamp": str(event.get("time", "")),
        "sender_id": str(event.get("user_id", event.get("target_id", ""))),
        "sender_name": str(sender.get("card") or sender.get("nickname") or ""),
        "mentioned": str(is_at_bot(event)).lower(),
    }
    message = ElementTree.SubElement(root, "message", attrs)
    if event.get("post_type") == "notice" and event.get("sub_type") == "poke":
        extension = ElementTree.SubElement(message, "extension", {"namespace": "qq", "name": "poke"})
        ElementTree.SubElement(extension, "param", {"name": "target_id"}).text = str(event.get("target_id", ""))
        return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)

    for segment in message_segments(event.get("message")):
        await _append_segment(message, event, segment, media, napcat)
    return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)


async def _append_segment(
    parent: ElementTree.Element, event: dict[str, Any], segment: dict[str, Any],
    media: HubMediaClient, napcat: NapcatGateway,
) -> None:
    segment_type = str(segment.get("type", ""))
    data = segment.get("data") if isinstance(segment.get("data"), dict) else {}
    if segment_type == "text":
        ElementTree.SubElement(parent, "text").text = str(data.get("text", ""))
        return
    if segment_type == "at":
        ElementTree.SubElement(parent, "mention", {"target_id": str(data.get("qq", ""))})
        return
    if segment_type == "reply":
        ElementTree.SubElement(parent, "quote", {"message_id": str(data.get("id", ""))})
        return
    if segment_type == "face":
        extension = ElementTree.SubElement(parent, "extension", {"namespace": "qq", "name": "face"})
        ElementTree.SubElement(extension, "param", {"name": "name"}).text = QQ_FACE_NAMES.get(str(data.get("id")), "未知表情")
        return
    if segment_type == "mface":
        extension = ElementTree.SubElement(parent, "extension", {"namespace": "qq", "name": "mface"})
        for key in ("emoji_package_id", "emoji_id", "summary"):
            if data.get(key) is not None:
                ElementTree.SubElement(extension, "param", {"name": key}).text = str(data[key])
        return
    if segment_type not in {"image", "file", "record", "video"}:
        return
    url = str(data.get("url", ""))
    if not url and segment_type == "file":
        url = await _resolve_file_url(data, napcat) or ""
    if not url:
        return
    stored = await media.store_url(url, _first(data, "file", "name"), _first(data, "mime"), segment_type)
    node_name = "audio" if segment_type == "record" else segment_type
    attrs = {"object_key": str(stored["object_key"]), "name": str(stored.get("name", ""))}
    if stored.get("mime"):
        attrs["mime_type"] = str(stored["mime"])
    ElementTree.SubElement(parent, node_name, attrs)


async def reply_to_items(xml: str, media: HubMediaClient) -> list[OutboundItem]:
    root = ElementTree.fromstring(xml)
    if root.tag != "reply":
        raise ValueError("reply root must be <reply>")
    items: list[OutboundItem] = []
    for node in list(root):
        if node.tag != "message":
            raise ValueError("reply only accepts <message>")
        target_id = node.get("target_id")
        mention = node.get("mention", "false").lower() == "true"
        pending: list[dict[str, Any]] = []

        def flush() -> None:
            if pending:
                items.append(OutboundMessage(list(pending), target_id, mention))
                pending.clear()

        for child in list(node):
            if child.tag == "text":
                pending.append({"type": "text", "data": {"text": child.text or ""}})
            elif child.tag == "mention":
                pending.append({"type": "at", "data": {"qq": _required(child, "target_id")}})
            elif child.tag == "quote":
                pending.append({"type": "reply", "data": {"id": _required(child, "message_id")}})
            elif child.tag == "image":
                pending.append({"type": "image", "data": {"file": await media.base64_file(_required(child, "object_key"))}})
            elif child.tag == "audio":
                pending.append({"type": "record", "data": {"file": await media.base64_file(_required(child, "object_key"))}})
            elif child.tag == "video":
                pending.append({"type": "video", "data": {"file": await media.base64_file(_required(child, "object_key"))}})
            elif child.tag == "file":
                flush()
                key = _required(child, "object_key")
                metadata = await media.metadata(key)
                items.append(OutboundFile(await media.base64_file(key), str(metadata.get("name", "file")), target_id))
            elif child.tag == "extension":
                namespace, name = child.get("namespace"), child.get("name")
                params = {param.get("name", ""): param.text or "" for param in list(child) if param.tag == "param"}
                if namespace != "qq" or name not in {"face", "poke"}:
                    raise ValueError("undeclared QQ output extension")
                if name == "face":
                    face_id = QQ_FACE_IDS.get(params.get("name", ""))
                    if face_id is None:
                        raise ValueError("unknown QQ face name")
                    pending.append({"type": "face", "data": {"id": face_id}})
                else:
                    flush()
                    poke_target = params.get("target_id") or target_id
                    if not poke_target:
                        raise ValueError("qq poke requires target_id")
                    items.append(OutboundPoke(poke_target))
            else:
                raise ValueError(f"unsupported reply node: {child.tag}")
        flush()
    return items


async def _resolve_file_url(data: dict[str, Any], napcat: NapcatGateway) -> str | None:
    file_id = _first(data, "file_id", "file", "id")
    if not file_id:
        return None
    for action in ("get_private_file_url", "get_file"):
        try:
            response = await napcat.action(action, {"file_id": file_id})
        except Exception:
            continue
        payload = response.get("data")
        if isinstance(payload, str) and payload.startswith(("http://", "https://")):
            return payload
        if isinstance(payload, dict):
            for key in ("url", "download_url", "file_url"):
                value = payload.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
    return None


def _first(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if data.get(key) is not None and str(data[key]).strip():
            return str(data[key])
    return None


def _required(node: ElementTree.Element, name: str) -> str:
    value = node.get(name)
    if not value:
        raise ValueError(f"{node.tag} requires {name}")
    return value
