from __future__ import annotations

import re
from typing import Any

from nonebot.adapters.onebot.v11.event import GroupMessageEvent, PrivateMessageEvent
from pydantic import TypeAdapter, ValidationError

from ..router.schemas import CleanResult, FilteredEventPayload, OutboundAction

MESSAGE_EVENT_ADAPTER = TypeAdapter(GroupMessageEvent | PrivateMessageEvent)
CQ_CODE_PATTERN = re.compile(r"\[CQ:[^\]]+\]")


class AdapterService:
    def clean_event(self, raw_event: dict[str, Any]) -> CleanResult:
        try:
            event = MESSAGE_EVENT_ADAPTER.validate_python(raw_event)
        except ValidationError:
            return CleanResult(accepted=False, ignore_reason="unsupported_event_type")

        if isinstance(event, GroupMessageEvent):
            # 业务策略收口：提醒中枢首版仅处理私聊，群聊统一在网关层过滤，
            # 可避免群消息进入后续链路造成无效 agent 触发与噪音扩散。
            return CleanResult(accepted=False, ignore_reason="group_message_ignored")

        plain_text = self._extract_plain_text(event)
        if not plain_text:
            return CleanResult(accepted=False, ignore_reason="empty_text_after_clean")

        user_id = int(event.get_user_id())
        message_type = "group" if isinstance(event, GroupMessageEvent) else "private"

        if message_type == "group":
            group_id = int(event.group_id)
            session_id = self.to_group_session_id(group_id)
        else:
            session_id = self.to_private_session_id(user_id)

        payload = FilteredEventPayload(
            session_id=session_id,
            user_id=self.to_abstract_user_id(user_id),
            content=plain_text,
            message_type=message_type,
            raw_event=raw_event,
        )

        return CleanResult(accepted=True, payload=payload)

    def build_send_message_action(self, session_id: str, content: str) -> OutboundAction:
        if session_id.startswith("group_"):
            group_id = self.parse_group_session_id(session_id)
            return OutboundAction(action="send_group_msg", params={"group_id": group_id, "message": content})

        if session_id.startswith("private_"):
            user_id = self.parse_private_session_id(session_id)
            return OutboundAction(action="send_private_msg", params={"user_id": user_id, "message": content})

        raise ValueError("session_id must start with 'group_' or 'private_'")

    def build_get_user_info_action(self, abstract_user_id: str) -> OutboundAction:
        user_id = self.parse_abstract_user_id(abstract_user_id)
        return OutboundAction(action="get_stranger_info", params={"user_id": user_id, "no_cache": True})

    def build_get_history_action(
        self,
        session_id: str,
        limit: int,
        before_message_id: int | None,
    ) -> OutboundAction:
        # 历史查询沿用 session 维度，agent 不需要关心 OneBot 的群/私聊底层差异。
        message_seq = before_message_id if before_message_id is not None else 0

        if session_id.startswith("group_"):
            group_id = self.parse_group_session_id(session_id)
            return OutboundAction(
                action="get_group_msg_history",
                params={"group_id": group_id, "count": limit, "message_seq": message_seq},
            )

        if session_id.startswith("private_"):
            user_id = self.parse_private_session_id(session_id)
            return OutboundAction(
                action="get_friend_msg_history",
                params={"user_id": user_id, "count": limit, "message_seq": message_seq},
            )

        raise ValueError("session_id must start with 'group_' or 'private_'")

    @staticmethod
    def normalize_history_result(session_id: str, raw_result: dict[str, Any]) -> dict[str, Any]:
        # 只稳定对外所需的最小字段，其余原始消息内容原样保留给 agent 做二次推理。
        if not isinstance(raw_result, dict):
            raise ValueError("history response must be a dict")

        payload = raw_result.get("data")
        if not isinstance(payload, dict):
            raise ValueError("history response data must be a dict")

        raw_messages = payload.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("history response messages must be a list")

        messages = [message for message in raw_messages if isinstance(message, dict)]
        next_before_message_id = AdapterService._extract_next_before_message_id(messages)

        return {
            "session_id": session_id,
            "messages": messages,
            "next_before_message_id": next_before_message_id,
        }

    @staticmethod
    def to_group_session_id(group_id: int) -> str:
        return f"group_{group_id}"

    @staticmethod
    def to_private_session_id(user_id: int) -> str:
        return f"private_{user_id}"

    @staticmethod
    def to_abstract_user_id(user_id: int) -> str:
        return f"qq_{user_id}"

    @staticmethod
    def parse_group_session_id(session_id: str) -> int:
        try:
            return int(session_id.split("group_", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid group session_id") from exc

    @staticmethod
    def parse_private_session_id(session_id: str) -> int:
        try:
            return int(session_id.split("private_", 1)[1])
        except (IndexError, ValueError) as exc:
            raise ValueError("invalid private session_id") from exc

    @staticmethod
    def parse_abstract_user_id(user_id: str) -> int:
        if not user_id.startswith("qq_"):
            raise ValueError("user_id must start with 'qq_'")

        try:
            return int(user_id.split("qq_", 1)[1])
        except ValueError as exc:
            raise ValueError("invalid abstract user_id") from exc

    @staticmethod
    def _extract_plain_text(event: GroupMessageEvent | PrivateMessageEvent) -> str:
        # 这里采用两级清洗：先用适配器 Message 的 extract_plain_text 获取语义文本，
        # 再用 CQ 正则兜底去除残留片段，避免上游实现差异导致 CQ 泄漏到业务层。
        plain_text = event.get_message().extract_plain_text()
        plain_text = CQ_CODE_PATTERN.sub("", plain_text)
        return plain_text.strip()

    @staticmethod
    def _extract_next_before_message_id(messages: list[dict[str, Any]]) -> int | None:
        # 选择最后一条有 message_id 的记录作为下一页游标，保证翻页不会倒退或跳号。
        for message in reversed(messages):
            message_id = message.get("message_id")
            if message_id is None:
                continue
            try:
                return int(message_id)
            except (TypeError, ValueError):
                continue
        return None
