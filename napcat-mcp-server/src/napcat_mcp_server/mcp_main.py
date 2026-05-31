import json
from mcp.server.fastmcp import FastMCP

from .mcp.client import NapcatMcpClient
from .mcp.config import get_settings


def create_server() -> FastMCP:
    settings = get_settings()
    client = NapcatMcpClient(
        base_url=settings.mcp.base_url,
        timeout_seconds=settings.mcp.timeout_seconds,
    )

    mcp = FastMCP(
        name="napcat-mcp-server",
        instructions="Expose OneBot v11 tools (message history, user info) for agents.",
    )

    @mcp.tool()
    async def qq_get_message_history(
        message_type: str,
        peer_id: int,
        limit: int = 20,
        before_message_id: int | None = None,
    ) -> str:
        """获取 QQ 聊天记录。

        Args:
            message_type: "group" 表示群聊，"private" 表示私聊。
            peer_id: 群号（message_type=group 时）或用户 QQ 号（message_type=private 时）。
            limit: 返回条数，1-50。
            before_message_id: 从该消息 ID 之前开始拉取，None 表示最新。
        """
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        if before_message_id is not None and before_message_id < 1:
            raise ValueError("before_message_id must be positive")
        if message_type not in ("group", "private"):
            raise ValueError("message_type must be 'group' or 'private'")

        result = await client.get_message_history(
            message_type=message_type,
            peer_id=peer_id,
            limit=limit,
            before_message_id=before_message_id,
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def qq_get_user_info(user_id: int) -> str:
        """获取 QQ 用户信息。

        Args:
            user_id: QQ 用户 ID。
        """
        if user_id < 1:
            raise ValueError("user_id must be positive")

        result = await client.get_user_info(user_id=user_id)
        return json.dumps(result, ensure_ascii=False)

    return mcp


def main() -> None:
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
