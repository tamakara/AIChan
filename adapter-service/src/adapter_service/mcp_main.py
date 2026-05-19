import json
from mcp.server.fastmcp import FastMCP

from .mcp.client import AdapterClient
from .mcp.config import get_settings


def create_server() -> FastMCP:
    settings = get_settings()
    adapter_client = AdapterClient(
        base_url=settings.base_url,
        timeout_seconds=settings.timeout_seconds,
    )

    mcp = FastMCP(
        name="adapter-service",
        instructions="Expose QQ message history as MCP tools for agents.",
    )

    @mcp.tool()
    async def qq_get_message_history(
        session_id: str,
        limit: int = 20,
        before_message_id: int | None = None,
    ) -> str:
        # MCP 侧只做参数边界与协议转换，避免把 QQ 协议细节泄漏给 agent。
        if limit < 1 or limit > 50:
            raise ValueError("limit must be between 1 and 50")
        if before_message_id is not None and before_message_id < 1:
            raise ValueError("before_message_id must be positive")
        if not (session_id.startswith("group_") or session_id.startswith("private_")):
            raise ValueError("session_id must start with 'group_' or 'private_'")

        result = await adapter_client.get_message_history(
            session_id=session_id,
            limit=limit,
            before_message_id=before_message_id,
        )
        return json.dumps(result, ensure_ascii=False)

    return mcp


def main() -> None:
    # MCP 工具是被 gateway 以子进程拉起，统一走 stdio 传输可复用 gateway 现有链路。
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

