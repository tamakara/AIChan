from agent_service.services.types.context import Context


def test_add_message_stores_base_fields() -> None:
    context = Context()

    context.add_message(role="user", content="hello")

    assert context.messages == [{"role": "user", "content": "hello"}]


def test_add_message_keeps_tool_call_fields() -> None:
    context = Context()

    context.add_message(
        role="assistant",
        content="",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],  # type: ignore[list-item]
    )
    context.add_message(role="tool", content='{"ok":true}', tool_call_id="call_1")

    assert context.messages[0]["tool_calls"][0]["id"] == "call_1"  # type: ignore[index]
    assert context.messages[1]["tool_call_id"] == "call_1"
