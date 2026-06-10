import argparse
import json

from mcp.server.fastmcp import FastMCP

from .mcp.client import ToolMcpClient
from .mcp.config import get_settings
from .mcp.vision import VisionClient


def create_server() -> FastMCP:
    settings = get_settings()
    client = ToolMcpClient(
        base_url=settings.mcp.base_url,
        timeout_seconds=settings.mcp.timeout_seconds,
    )
    vision_client = VisionClient(settings.vision)

    mcp = FastMCP(
        name="tool-mcp-server",
        instructions="Expose AICHAN custom tools for QQ context, text files, image understanding, and video understanding.",
        host=settings.server.host,
        port=settings.server.port,
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

    @mcp.tool()
    async def file_get_metadata(object_key: str) -> str:
        """获取 hub-service 已入库文件的元数据。

        Args:
            object_key: `<image>` / `<file>` 等消息节点上的 object_key。
        """
        result = await client.get_file_metadata(object_key=object_key)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def file_read_text(object_key: str, max_chars: int = 12000) -> str:
        """按 UTF-8 文本读取 hub-service 已入库文件。

        Args:
            object_key: `<file>` 消息节点上的 object_key。
            max_chars: 最大返回字符数，1-50000。
        """
        if max_chars < 1 or max_chars > 50000:
            raise ValueError("max_chars must be between 1 and 50000")

        result = await client.read_file_text(object_key=object_key, max_chars=max_chars)
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def image_describe(object_key: str, question: str | None = None) -> str:
        """理解 hub-service 已入库图片，并按问题返回描述。

        Args:
            object_key: `<image>` 消息节点上的 object_key。
            question: 针对图片的具体问题；为空时返回通用描述。
        """
        result = await describe_image_object(
            client=client,
            vision_client=vision_client,
            object_key=object_key,
            question=question,
        )
        return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    async def video_describe(object_key: str, question: str | None = None) -> str:
        """理解 hub-service 已入库视频，并按问题返回描述。

        Args:
            object_key: `<video>` 消息节点上的 object_key。
            question: 针对视频的具体问题；为空时返回通用描述。
        """
        result = await describe_video_object(
            client=client,
            vision_client=vision_client,
            object_key=object_key,
            question=question,
        )
        return json.dumps(result, ensure_ascii=False)

    return mcp


async def describe_image_object(
    *,
    client: ToolMcpClient,
    vision_client: VisionClient,
    object_key: str,
    question: str | None,
) -> dict[str, str | None]:
    metadata = await client.get_file_metadata(object_key=object_key)
    mime = str(metadata.get("mime") or "")
    if not mime.startswith("image/"):
        raise ValueError("object_key must point to an image")

    content = await client.get_file_content(object_key=object_key)
    description = await vision_client.describe(content=content, mime=mime, question=question)
    return {
        "type": "image_description",
        "object_key": object_key,
        "mime": mime,
        "description": description,
        "question": question,
        "answer": description,
    }


async def describe_video_object(
    *,
    client: ToolMcpClient,
    vision_client: VisionClient,
    object_key: str,
    question: str | None,
) -> dict[str, str | None]:
    metadata = await client.get_file_metadata(object_key=object_key)
    mime = str(metadata.get("mime") or "")
    if not mime.startswith("video/"):
        raise ValueError("object_key must point to a video")

    content = await client.get_file_content(object_key=object_key)
    description = await vision_client.describe_video(content=content, mime=mime, question=question)
    return {
        "type": "video_description",
        "object_key": object_key,
        "mime": mime,
        "description": description,
        "question": question,
        "answer": description,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=("stdio", "sse", "streamable-http"),
        default="stdio",
    )
    args = parser.parse_args()

    server = create_server()
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
