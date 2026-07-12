# core-mcp-server

core-mcp-server 是单一 Streamable HTTP MCP 服务，只包含：

- `file_get_metadata`
- `file_read_text`
- `memory_get_user_memory`
- `image_describe`
- `video_describe`

Adapter capability 不经过 MCP 回环，由 Core 根据在线 Manifest 直接生成和调用。服务复用 file-service 与 memory-service 的异步连接池，MCP Gateway 通过 `core-mcp-server/docker-mcp-catalog.yml` 加载工具。
