from channel_service.mcp_main import create_server


def test_create_server_has_history_tool() -> None:
    server = create_server()
    tool_names = list(server._tool_manager._tools.keys())  # type: ignore[attr-defined]
    assert "onebot_get_message_history" in tool_names
