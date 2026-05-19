import pytest

from channel_service.services.channel_service import AdapterService


@pytest.fixture
def service() -> AdapterService:
    return AdapterService()


def test_id_mapping_roundtrip(service: AdapterService) -> None:
    assert service.to_group_session_id(123) == "group_123"
    assert service.to_private_session_id(456) == "private_456"
    assert service.to_abstract_user_id(789) == "onebot_789"

    assert service.parse_group_session_id("group_123") == 123
    assert service.parse_private_session_id("private_456") == 456
    assert service.parse_abstract_user_id("onebot_789") == 789


def test_private_text_clean_pass(service: AdapterService) -> None:
    raw = {
        "time": 1710000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 11,
        "user_id": 20002,
        "message": [{"type": "text", "data": {"text": "?? [CQ:image,file=a.png] ??"}}],
        "raw_message": "?? [CQ:image,file=a.png] ??",
        "font": 14,
        "sender": {"user_id": 20002, "nickname": "alice", "sex": "unknown", "age": 0},
    }
    result = service.clean_event(raw)
    assert result.accepted is True
    assert result.payload is not None
    assert result.payload.session_id == "private_20002"
    assert result.payload.user_id == "onebot_20002"
    assert result.payload.content == "??  ??"


def test_group_without_at_ignored(service: AdapterService) -> None:
    raw = {
        "time": 1710000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 12,
        "group_id": 30003,
        "user_id": 20002,
        "message": [{"type": "text", "data": {"text": "hello"}}],
        "raw_message": "hello",
        "font": 14,
        "sender": {
            "user_id": 20002,
            "nickname": "alice",
            "card": "",
            "sex": "unknown",
            "age": 0,
            "area": "",
            "level": "",
            "role": "member",
            "title": "",
        },
    }
    result = service.clean_event(raw)
    assert result.accepted is False
    assert result.ignore_reason == "group_message_ignored"


def test_group_with_at_still_ignored(service: AdapterService) -> None:
    raw = {
        "time": 1710000000,
        "self_id": 10001,
        "post_type": "message",
        "message_type": "group",
        "sub_type": "normal",
        "message_id": 13,
        "group_id": 30003,
        "user_id": 20002,
        "message": [
            {"type": "at", "data": {"qq": "10001"}},
            {"type": "text", "data": {"text": "  ??? "}},
        ],
        "raw_message": "[CQ:at,qq=10001] ???",
        "font": 14,
        "sender": {
            "user_id": 20002,
            "nickname": "alice",
            "card": "",
            "sex": "unknown",
            "age": 0,
            "area": "",
            "level": "",
            "role": "member",
            "title": "",
        },
    }
    result = service.clean_event(raw)
    assert result.accepted is False
    assert result.ignore_reason == "group_message_ignored"


def test_build_send_message_action_group(service: AdapterService) -> None:
    action = service.build_send_message_action("group_123", "hi")
    assert action.action == "send_group_msg"
    assert action.params["group_id"] == 123


def test_build_send_message_action_private(service: AdapterService) -> None:
    action = service.build_send_message_action("private_456", "hi")
    assert action.action == "send_private_msg"
    assert action.params["user_id"] == 456


def test_build_get_user_info_action(service: AdapterService) -> None:
    action = service.build_get_user_info_action("onebot_777")
    assert action.action == "get_stranger_info"
    assert action.params["user_id"] == 777


def test_build_get_history_action_group(service: AdapterService) -> None:
    action = service.build_get_history_action("group_123", 20, 88)
    assert action.action == "get_group_msg_history"
    assert action.params["group_id"] == 123
    assert action.params["count"] == 20
    assert action.params["message_seq"] == 88


def test_build_get_history_action_private(service: AdapterService) -> None:
    action = service.build_get_history_action("private_456", 10, None)
    assert action.action == "get_friend_msg_history"
    assert action.params["user_id"] == 456
    assert action.params["count"] == 10
    assert action.params["message_seq"] == 0


def test_normalize_history_result(service: AdapterService) -> None:
    result = service.normalize_history_result(
        session_id="private_456",
        raw_result={
            "status": "ok",
            "retcode": 0,
            "data": {
                "messages": [
                    {"message_id": "11", "text": "old"},
                    {"message_id": 12, "text": "new"},
                ]
            },
        },
    )
    assert result["session_id"] == "private_456"
    assert len(result["messages"]) == 2
    assert result["next_before_message_id"] == 12


def test_invalid_session_prefix(service: AdapterService) -> None:
    with pytest.raises(ValueError):
        service.build_send_message_action("foo_1", "bad")
