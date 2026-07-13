from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from xml.etree import ElementTree

from defusedxml import ElementTree as SafeElementTree
from jsonschema import validate

from .protocol import AdapterRegistration, ExtensionDefinition

INPUT_TAGS = {"text", "file", "mention", "quote", "extension"}
OUTPUT_TAGS = {"text", "file", "extension"}


@dataclass(frozen=True)
class ParsedXml:
    xml: str
    file_refs: frozenset[str]


class XmlMessageCodec:
    """XML v2 的唯一解析入口，集中执行结构、扩展和媒体引用约束。"""

    def __init__(self, max_xml_bytes: int = 262_144) -> None:
        self._max_xml_bytes = max_xml_bytes

    def validate_messages(self, raw: str, registration: AdapterRegistration, *, allow_empty: bool = False) -> ParsedXml:
        root = self._parse(raw, "messages")
        if not list(root) and not allow_empty:
            raise ValueError("<messages> 至少包含一个 <message>")
        keys: set[str] = set()
        for message in list(root):
            self._validate_input_message(message, registration, keys)
        return ParsedXml(self._serialize(root), frozenset(keys))

    def validate_reply(self, raw: str, registration: AdapterRegistration, allowed_file_refs: set[str] | frozenset[str]) -> ParsedXml:
        root = self._parse(raw, "reply")
        keys: set[str] = set()
        for message in list(root):
            self._validate_output_message(message, registration, keys)
        unknown = keys - set(allowed_file_refs)
        if unknown:
            raise ValueError(f"reply 引用了未知 file ref: {sorted(unknown)[0]}")
        return ParsedXml(self._serialize(root), frozenset(keys))

    def merge_messages(self, items: list[str], registration: AdapterRegistration) -> ParsedXml:
        root = ElementTree.Element("messages")
        keys: set[str] = set()
        for raw in items:
            parsed_root = self._parse(raw, "messages")
            for message in list(parsed_root):
                self._validate_input_message(message, registration, keys)
                root.append(message)
        if not list(root):
            raise ValueError("<messages> 至少包含一个 <message>")
        return ParsedXml(self._serialize(root), frozenset(keys))

    @staticmethod
    def text_reply(text: str) -> str:
        root = ElementTree.Element("reply")
        message = ElementTree.SubElement(root, "message")
        child = ElementTree.SubElement(message, "text")
        child.text = text
        return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)

    def _parse(self, raw: str, expected_root: str) -> ElementTree.Element:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > self._max_xml_bytes:
            raise ValueError("XML payload 超过大小限制")
        upper = raw.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise ValueError("XML 禁止 DTD 和 ENTITY")
        try:
            root = SafeElementTree.fromstring(raw)
        except Exception as exc:
            raise ValueError("XML 无法解析") from exc
        if root.tag != expected_root or root.attrib or (root.text and root.text.strip()):
            raise ValueError(f"XML 根节点必须是无属性的 <{expected_root}>")
        return root

    def _validate_input_message(self, message: ElementTree.Element, registration: AdapterRegistration, keys: set[str]) -> None:
        if message.tag != "message":
            raise ValueError("<messages> 只接受 <message>")
        required = {"id", "timestamp", "sender_id"}
        allowed = required | {"sender_name", "mentioned"}
        self._validate_attributes(message, required, allowed)
        if not message.get("timestamp", "").isdigit():
            raise ValueError("message timestamp 必须是 Unix 秒")
        self._parse_bool(message.get("mentioned", "false"))
        self._validate_parts(message, INPUT_TAGS, registration, "input", keys)

    def _validate_output_message(self, message: ElementTree.Element, registration: AdapterRegistration, keys: set[str]) -> None:
        if message.tag != "message":
            raise ValueError("<reply> 只接受 <message>")
        self._validate_attributes(message, set(), {"target_id", "target_name", "mention"})
        self._parse_bool(message.get("mention", "false"))
        if not list(message):
            raise ValueError("reply message 至少包含一个内容节点")
        self._validate_parts(message, OUTPUT_TAGS, registration, "output", keys)

    def _validate_parts(self, message: ElementTree.Element, allowed: set[str], registration: AdapterRegistration, direction: Literal["input", "output"], keys: set[str]) -> None:
        if not list(message):
            raise ValueError("message 至少包含一个内容节点")
        declarations = {item.type: item for item in registration.extensions if direction in item.directions}
        for child in list(message):
            if child.tag not in allowed:
                raise ValueError(f"{direction} 不支持节点: {child.tag}")
            if child.tag == "text":
                if child.attrib or list(child):
                    raise ValueError("text 只能包含文本")
            elif child.tag == "file":
                self._validate_attributes(child, {"ref"}, {"ref", "name"})
                file_ref = child.get("ref", "")
                if len(file_ref) > 512:
                    raise ValueError("file ref 长度不能超过 512")
                keys.add(file_ref)
            elif child.tag == "mention":
                self._validate_attributes(child, {"target_id"}, {"target_id"})
            elif child.tag == "quote":
                self._validate_attributes(child, {"message_id"}, {"message_id"})
            else:
                self._validate_extension(child, declarations)

    def _validate_extension(self, node: ElementTree.Element, declarations: dict[str, ExtensionDefinition]) -> None:
        if list(node) or (node.text and node.text.strip()):
            raise ValueError("extension 只能使用扁平属性")
        extension_type = node.get("type", "")
        definition = declarations.get(extension_type)
        if definition is None:
            raise ValueError("extension 未为当前方向声明")
        raw_arguments = {key: value for key, value in node.attrib.items() if key != "type"}
        properties = definition.parameters_schema.get("properties", {})
        converted: dict[str, Any] = {}
        for name, value in raw_arguments.items():
            schema = properties.get(name)
            if not isinstance(schema, dict):
                raise ValueError(f"extension 包含未知参数: {name}")
            converted[name] = self._convert_scalar(value, str(schema["type"]))
        validate(converted, definition.parameters_schema)

    @staticmethod
    def _convert_scalar(value: str, kind: str) -> Any:
        try:
            if kind == "string":
                return value
            if kind == "integer":
                return int(value)
            if kind == "number":
                return float(value)
            if kind == "boolean":
                return XmlMessageCodec._parse_bool(value)
        except ValueError as exc:
            raise ValueError(f"extension 参数无法转换为 {kind}") from exc
        raise ValueError(f"不支持的 extension 参数类型: {kind}")

    @staticmethod
    def _parse_bool(value: str) -> bool:
        if value not in {"true", "false"}:
            raise ValueError("布尔属性只能是 true 或 false")
        return value == "true"

    @staticmethod
    def _validate_attributes(node: ElementTree.Element, required: set[str], allowed: set[str]) -> None:
        missing = required - set(node.attrib)
        unknown = set(node.attrib) - allowed
        if missing:
            raise ValueError(f"{node.tag} 缺少属性: {sorted(missing)[0]}")
        if unknown:
            raise ValueError(f"{node.tag} 包含未知属性: {sorted(unknown)[0]}")
        for name in required:
            if not node.get(name):
                raise ValueError(f"{node.tag} 属性不能为空: {name}")

    @staticmethod
    def _serialize(root: ElementTree.Element) -> str:
        return ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
