# tool-mcp-server

该服务向 agent 暴露通用 MCP 工具，不包含 QQ 专属工具或 URL。

核心工具：

- `adapter_invoke(session_id, capability, arguments)`：调用当前会话所属适配器声明的查询能力，经 hub WebSocket RPC 路由。
- `file_get_metadata`、`file_read_text`。
- `image_describe`、`video_describe`。
- `memory_get_user_memory`。

`mcp.hub_base_url` 指向 hub-service；`mcp.file_base_url` 和 `mcp.memory_base_url` 分别指向文件与记忆服务。适配器 capability 的名称和参数由当前 adapter skill 告知模型。
