from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape

from nonebot.adapters.onebot.v11.event import (
    FriendRecallNoticeEvent,
    GroupMessageEvent,
    GroupRecallNoticeEvent,
    PokeNotifyEvent,
    PrivateMessageEvent,
)
from pydantic import TypeAdapter, ValidationError

from ..router.schemas import CleanResult, FilteredEventPayload, OutboundAction

MESSAGE_EVENT_ADAPTER = TypeAdapter(GroupMessageEvent | PrivateMessageEvent)
NOTICE_EVENT_ADAPTER = TypeAdapter(PokeNotifyEvent | FriendRecallNoticeEvent | GroupRecallNoticeEvent)
CQ_CODE_PATTERN = re.compile(r"\[CQ:[^\]]+\]")


class AdapterService:
    def __init__(self, allowed_message_types: set[str]) -> None:
        self._allowed_message_types = allowed_message_types

    def clean_event(self, raw_event: dict[str, Any]) -> CleanResult:
        if self._is_supported_post_type(raw_event) and self._extract_event_time(raw_event) is None:
            return CleanResult(accepted=False, ignore_reason="missing_event_time")

        try:
            message_event = MESSAGE_EVENT_ADAPTER.validate_python(raw_event)
        except ValidationError:
            message_event = None

        if message_event is not None:
            return self._clean_message_event(raw_event=raw_event, event=message_event)

        try:
            notice_event = NOTICE_EVENT_ADAPTER.validate_python(raw_event)
        except ValidationError:
            return CleanResult(accepted=False, ignore_reason="unsupported_event_type")

        return self._clean_notice_event(raw_event=raw_event, event=notice_event)

    def _clean_message_event(
        self,
        *,
        raw_event: dict[str, Any],
        event: GroupMessageEvent | PrivateMessageEvent,
    ) -> CleanResult:
        plain_text = self._extract_plain_text(event)
        if not plain_text:
            return CleanResult(accepted=False, ignore_reason="empty_text_after_clean")

        message_id = self._extract_message_id(raw_event=raw_event, event=event)
        if message_id is None:
            return CleanResult(accepted=False, ignore_reason="missing_message_id")

        event_time = self._extract_event_time(raw_event)
        if event_time is None:
            return CleanResult(accepted=False, ignore_reason="missing_event_time")

        user_id = int(event.get_user_id())
        abstract_user_id = self.to_abstract_user_id(user_id)
        if isinstance(event, GroupMessageEvent):
            message_type = "group"
            group_id = int(event.group_id)
            session_id = self.to_group_session_id(group_id)
        else:
            message_type = "private"
            session_id = self.to_private_session_id(user_id)

        if not self._is_allowed_message_type(message_type):
            return CleanResult(accepted=False, ignore_reason="message_type_filtered")

        sub_type = self._extract_sub_type(raw_event=raw_event, event=event)

        payload = FilteredEventPayload(
            session_id=session_id,
            event_xml=self._build_message_event_xml(
                message_type=message_type,
                sub_type=sub_type,
                message_id=message_id,
                session_id=session_id,
                user_id=abstract_user_id,
                event_time=event_time,
                content=plain_text,
            ),
            raw_event=raw_event,
        )

        return CleanResult(accepted=True, payload=payload)

    def _clean_notice_event(
        self,
        *,
        raw_event: dict[str, Any],
        event: PokeNotifyEvent | FriendRecallNoticeEvent | GroupRecallNoticeEvent,
    ) -> CleanResult:
        event_time = self._extract_event_time(raw_event)
        if event_time is None:
            return CleanResult(accepted=False, ignore_reason="missing_event_time")

        # Notice 事件不带 message_type 字段，需根据 group_id 是否存在推导会话类型，
        # 才能复用与消息事件一致的 group/private 白名单策略。
        if isinstance(event, PokeNotifyEvent):
            group_id = event.group_id
            actor_user_id = int(event.user_id)
            target_user_id = int(event.target_id)
            return self._clean_poke_notice_event(
                group_id=group_id,
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                raw_event=raw_event,
            )

        if isinstance(event, GroupRecallNoticeEvent):
            return self._clean_recall_notice_event(
                message_type="group",
                session_id=self.to_group_session_id(int(event.group_id)),
                actor_user_id=int(event.user_id),
                message_id=str(event.message_id),
                raw_event=raw_event,
            )

        return self._clean_recall_notice_event(
            message_type="private",
            session_id=self.to_private_session_id(int(event.user_id)),
            actor_user_id=int(event.user_id),
            message_id=str(event.message_id),
            raw_event=raw_event,
        )

    def _clean_poke_notice_event(
        self,
        *,
        group_id: int | None,
        actor_user_id: int,
        target_user_id: int,
        raw_event: dict[str, Any],
    ) -> CleanResult:
        if group_id is not None:
            message_type = "group"
            session_id = self.to_group_session_id(int(group_id))
        else:
            message_type = "private"
            session_id = self.to_private_session_id(actor_user_id)

        if not self._is_allowed_message_type(message_type):
            return CleanResult(accepted=False, ignore_reason="message_type_filtered")

        payload = FilteredEventPayload(
            session_id=session_id,
            event_xml=self._build_poke_event_xml(
                session_id=session_id,
                user_id=self.to_abstract_user_id(actor_user_id),
                target_id=self.to_abstract_user_id(target_user_id),
            ),
            raw_event=raw_event,
        )
        return CleanResult(accepted=True, payload=payload)

    def _clean_recall_notice_event(
        self,
        *,
        message_type: str,
        session_id: str,
        actor_user_id: int,
        message_id: str,
        raw_event: dict[str, Any],
    ) -> CleanResult:
        if not self._is_allowed_message_type(message_type):
            return CleanResult(accepted=False, ignore_reason="message_type_filtered")

        payload = FilteredEventPayload(
            session_id=session_id,
            event_xml=self._build_recall_event_xml(
                session_id=session_id,
                user_id=self.to_abstract_user_id(actor_user_id),
                message_id=message_id,
            ),
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
    def _extract_message_id(
        *,
        raw_event: dict[str, Any],
        event: GroupMessageEvent | PrivateMessageEvent,
    ) -> str | None:
        raw_message_id = raw_event.get("message_id")
        if raw_message_id is not None:
            return str(raw_message_id)
        message_id = getattr(event, "message_id", None)
        if message_id is None:
            return None
        return str(message_id)

    @staticmethod
    def _extract_event_time(raw_event: dict[str, Any]) -> str | None:
        time_value = raw_event.get("time")
        if isinstance(time_value, bool):
            return None
        if isinstance(time_value, int):
            return str(time_value)
        if isinstance(time_value, float) and time_value.is_integer():
            return str(int(time_value))
        if isinstance(time_value, str) and time_value.strip().isdigit():
            return str(int(time_value.strip()))
        return None

    @staticmethod
    def _extract_sub_type(
        *,
        raw_event: dict[str, Any],
        event: GroupMessageEvent | PrivateMessageEvent,
    ) -> str:
        raw_sub_type = raw_event.get("sub_type")
        if isinstance(raw_sub_type, str) and raw_sub_type:
            return raw_sub_type
        event_sub_type = getattr(event, "sub_type", "")
        return str(event_sub_type)

    def _is_allowed_message_type(self, message_type: str) -> bool:
        return message_type in self._allowed_message_types

    @staticmethod
    def _is_supported_post_type(raw_event: dict[str, Any]) -> bool:
        post_type = raw_event.get("post_type")
        return isinstance(post_type, str) and post_type in {"message", "notice"}

    @staticmethod
    def _build_message_event_xml(
        *,
        message_type: str,
        sub_type: str,
        message_id: str,
        session_id: str,
        user_id: str,
        event_time: str,
        content: str,
    ) -> str:
        # 入流阶段一次性固化协议 XML，确保 hub/agent 不再重复做字段拼装与转义。
        return (
            '<message '
            f'message_type="{AdapterService._escape_attr(message_type)}" '
            f'sub_type="{AdapterService._escape_attr(sub_type)}" '
            f'message_id="{AdapterService._escape_attr(message_id)}" '
            f'session_id="{AdapterService._escape_attr(session_id)}" '
            f'user_id="{AdapterService._escape_attr(user_id)}" '
            f'time="{AdapterService._escape_attr(event_time)}"'
            ">"
            f"{AdapterService._escape_text(content)}"
            "</message>"
        )

    @staticmethod
    def _build_poke_event_xml(
        *,
        session_id: str,
        user_id: str,
        target_id: str,
    ) -> str:
        return (
            "<poke "
            f'session_id="{AdapterService._escape_attr(session_id)}" '
            f'user_id="{AdapterService._escape_attr(user_id)}" '
            f'target_id="{AdapterService._escape_attr(target_id)}" '
            "/>"
        )

    @staticmethod
    def _build_recall_event_xml(
        *,
        session_id: str,
        user_id: str,
        message_id: str,
    ) -> str:
        return (
            "<recall "
            f'session_id="{AdapterService._escape_attr(session_id)}" '
            f'user_id="{AdapterService._escape_attr(user_id)}" '
            f'message_id="{AdapterService._escape_attr(message_id)}" '
            "/>"
        )

    @staticmethod
    def _escape_attr(value: str) -> str:
        return escape(value, entities={'"': "&quot;"})

    @staticmethod
    def _escape_text(value: str) -> str:
        return escape(value)

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
