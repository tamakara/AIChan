import asyncio

from adapter_service.services.action_consumer import ActionConsumerWorker
from adapter_service.services.adapter_service import AdapterService
from adapter_service.services.connection_state import NapcatConnectionState
from adapter_service.services.napcat_ws_gateway import NapcatWsGateway


class StubRedisStream:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def read_pending_actions(self, count: int):
        return []

    async def read_new_actions(self, count: int):
        return []

    async def ack_action(self, message_id: str) -> None:
        self.acked.append(message_id)


class StubNapcatGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, dict]] = []

    async def send_action(self, websocket, action: str, params: dict):
        self.calls.append((websocket, action, params))
        return {"status": "ok", "retcode": 0, "data": {"message_id": 1}}


def test_action_consumer_ack_on_success() -> None:
    redis_stream = StubRedisStream()
    napcat_gateway = StubNapcatGateway()
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    worker = ActionConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        napcat_gateway=napcat_gateway,  # type: ignore[arg-type]
        napcat_connection_state=state,
        adapter_service=AdapterService(allowed_message_types={"private"}),
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "action_id": "a1",
                        "session_id": "private_1",
                        "action_xml": '<message session_id="private_1">hello</message>',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert len(napcat_gateway.calls) == 1
    _, action, params = napcat_gateway.calls[0]
    assert action == "send_private_msg"
    assert params == {"user_id": 1, "message": "hello"}


def test_action_consumer_executes_poke_and_recall_actions() -> None:
    redis_stream = StubRedisStream()
    napcat_gateway = StubNapcatGateway()
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    worker = ActionConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        napcat_gateway=napcat_gateway,  # type: ignore[arg-type]
        napcat_connection_state=state,
        adapter_service=AdapterService(allowed_message_types={"private", "group"}),
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "action_id": "a1",
                        "session_id": "group_2",
                        "action_xml": '<poke session_id="group_2" target_id="qq_3" />',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                ),
                (
                    "2-0",
                    {
                        "action_id": "a2",
                        "session_id": "group_2",
                        "action_xml": '<recall session_id="group_2" message_id="22" />',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                ),
            ]
        )
    )

    assert redis_stream.acked == ["1-0", "2-0"]
    assert napcat_gateway.calls[0][1] == "group_poke"
    assert napcat_gateway.calls[0][2] == {"group_id": 2, "user_id": 3}
    assert napcat_gateway.calls[1][1] == "delete_msg"
    assert napcat_gateway.calls[1][2] == {"message_id": 22}


def test_action_consumer_executes_friend_poke_and_group_message() -> None:
    redis_stream = StubRedisStream()
    napcat_gateway = StubNapcatGateway()
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    worker = ActionConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        napcat_gateway=napcat_gateway,  # type: ignore[arg-type]
        napcat_connection_state=state,
        adapter_service=AdapterService(allowed_message_types={"private", "group"}),
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "action_id": "a1",
                        "session_id": "private_2",
                        "action_xml": '<poke session_id="private_2" target_id="qq_3" />',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                ),
                (
                    "2-0",
                    {
                        "action_id": "a2",
                        "session_id": "group_7",
                        "action_xml": '<message session_id="group_7">hello group</message>',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                ),
            ]
        )
    )

    assert redis_stream.acked == ["1-0", "2-0"]
    assert napcat_gateway.calls[0][1] == "friend_poke"
    assert napcat_gateway.calls[0][2] == {"user_id": 3}
    assert napcat_gateway.calls[1][1] == "send_group_msg"
    assert napcat_gateway.calls[1][2] == {"group_id": 7, "message": "hello group"}


def test_action_consumer_invalid_action_xml_is_acked_and_dropped() -> None:
    redis_stream = StubRedisStream()
    napcat_gateway = StubNapcatGateway()
    state = NapcatConnectionState()
    state.set(object())  # type: ignore[arg-type]
    worker = ActionConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        napcat_gateway=napcat_gateway,  # type: ignore[arg-type]
        napcat_connection_state=state,
        adapter_service=AdapterService(allowed_message_types={"private", "group"}),
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "action_id": "a1",
                        "session_id": "group_2",
                        "action_xml": '<poke session_id="group_2" />',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == ["1-0"]
    assert napcat_gateway.calls == []


def test_action_consumer_no_ack_when_runtime_failed() -> None:
    redis_stream = StubRedisStream()
    napcat_gateway = StubNapcatGateway()
    state = NapcatConnectionState()
    worker = ActionConsumerWorker(
        redis_stream=redis_stream,  # type: ignore[arg-type]
        napcat_gateway=napcat_gateway,  # type: ignore[arg-type]
        napcat_connection_state=state,
        adapter_service=AdapterService(allowed_message_types={"private"}),
    )

    asyncio.run(
        worker._handle_batch(  # type: ignore[attr-defined]
            [
                (
                    "1-0",
                    {
                        "action_id": "a1",
                        "session_id": "private_1",
                        "action_xml": '<message session_id="private_1">hello</message>',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                )
            ]
        )
    )

    assert redis_stream.acked == []

