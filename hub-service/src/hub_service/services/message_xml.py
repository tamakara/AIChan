from __future__ import annotations

from typing import Any
from xml.etree import ElementTree

INPUT_SEGMENT_ATTRS: dict[str, tuple[str, ...]] = {
    "image": ("file", "url", "type"),
    "face": ("id",),
    "reply": ("id",),
    "record": ("file", "url"),
    "video": ("file", "url"),
    "at": ("qq",),
    "share": ("url", "title", "content", "image"),
    "location": ("lat", "lon", "title", "content"),
    "contact": ("type", "id"),
}

OUTPUT_SEGMENT_ATTRS: dict[str, tuple[str, ...]] = {
    "image": ("file",),
    "face": ("id",),
    "record": ("file",),
    "video": ("file",),
}


def onebot_private_events_to_input_xml(events: list[dict[str, Any]]) -> str:
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
        for segment in _message_segments(event.get("message")):
            _append_input_segment(message, segment)
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


def _append_input_segment(parent: ElementTree.Element, segment: dict[str, Any]) -> None:
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


def _set_attr(attrs: dict[str, str], name: str, value: object) -> None:
    if value is None:
        return
    attrs[name] = str(value)
