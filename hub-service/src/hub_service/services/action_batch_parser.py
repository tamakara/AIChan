from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedActionXml:
    session_id: str
    action_xml: str


def parse_action_batch(
    *,
    batch_xml: str,
    expected_session_id: str,
) -> list[ParsedActionXml]:
    try:
        root = ET.fromstring(batch_xml)
    except ET.ParseError as exc:
        raise ValueError("agent output must be valid xml") from exc

    if root.tag != "batch":
        raise ValueError("agent output root tag must be <batch>")
    if root.attrib.get("type") != "end":
        raise ValueError("agent output batch.type must be 'end'")
    if len(root) == 0:
        raise ValueError("agent output batch must include at least one event")

    actions: list[ParsedActionXml] = []
    for child in root:
        session_id = child.attrib.get("session_id", "").strip()
        if not session_id:
            raise ValueError(f"agent output <{child.tag}> missing session_id")
        if session_id != expected_session_id:
            raise ValueError(
                f"agent output <{child.tag}> session_id mismatch: expected={expected_session_id} actual={session_id}"
            )

        _validate_action_node(child)
        action_xml = ET.tostring(child, encoding="unicode", short_empty_elements=True).strip()
        actions.append(ParsedActionXml(session_id=session_id, action_xml=action_xml))
    return actions


def _validate_action_node(node: ET.Element) -> None:
    # 这里强制最小动作属性，确保 adapter 执行层拿到的 action_xml 可以直接映射到 NapCat action，
    # 避免“语义不完整但结构看似合法”的输出进入执行链路。
    if node.tag == "message":
        content = (node.text or "").strip()
        if not content:
            raise ValueError("agent output <message> content must be non-empty")
        return

    if node.tag == "poke":
        target_id = node.attrib.get("target_id", "").strip()
        if not target_id:
            raise ValueError("agent output <poke> missing target_id")
        return

    if node.tag == "recall":
        message_id = node.attrib.get("message_id", "").strip()
        if not message_id:
            raise ValueError("agent output <recall> missing message_id")
        return

    raise ValueError(f"agent output contains unsupported tag: {node.tag}")
