# tool-mcp-server

## 1. 模块定位

`tool-mcp-server` 是 AICHAN 自定义 MCP 工具层。它不直接连接 NapCat，不持有 MinIO 凭证；QQ 查询、文件读取和图片内容获取都通过 HTTP 调用 `hub-service`，由 hub-service 统一复用 NapCat WS 和私有 MinIO。

## 2. 启动方式

Compose 中的常驻 `tool-mcp-server` 容器直接运行 MCP 网络服务：

```bash
tool-mcp-mcp --transport streamable-http
```

MCP Gateway 通过 `tool-mcp-server/docker-mcp-catalog.yml` 中的 remote server 定义连接 `http://tool-mcp-server:8030/mcp`。这样 vision 的 `VISION__...` 环境变量会直接注入到常驻 `tool-mcp-server` service，而不是丢在 gateway 临时 `docker run` 的子容器外面。

## 3. MCP 工具

| 工具 | 说明 |
|------|------|
| `qq_get_message_history` | 查询私聊或群聊历史消息 |
| `qq_get_user_info` | 查询用户信息 |
| `file_get_metadata` | 根据 `object_key` 查询文件元数据 |
| `file_read_text` | 根据 `object_key` 读取文本类文件，非文本由 hub-service 返回 422 |
| `image_describe` | 根据 `object_key` 读取图片 bytes，调用独立 vision 模型生成描述或回答问题 |

`image_describe` 返回 JSON 字符串：

```json
{
  "type": "image_description",
  "object_key": "qq/private/1/9/0-abc.jpg",
  "mime": "image/jpeg",
  "description": "...",
  "question": "...",
  "answer": "..."
}
```

## 4. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | HTTP 健康检查服务监听地址 |
| `server.port` | int | HTTP 健康检查服务监听端口 |
| `mcp.base_url` | str | hub-service HTTP API 地址，当前指向 `http://hub-service:8020` |
| `mcp.timeout_seconds` | float | 调用 hub-service 的超时秒数 |
| `vision.openai_base_url` | str | OpenAI 兼容 vision API 地址 |
| `vision.openai_api_key` | str | vision API Key |
| `vision.model` | str | vision 模型名 |
| `vision.timeout_seconds` | float | vision 请求超时秒数 |

配置加载由 `pydantic-settings` 统一处理，优先级为：显式初始化参数 > 环境变量 > 根目录 `.env` > `tool-mcp-server/config.yml`。内部 `mcp.base_url` 和 timeout 固定维护在 `config.yml`；vision 只把 key、base URL、模型名放到环境变量，例如 `VISION__OPENAI_API_KEY`、`VISION__OPENAI_BASE_URL`、`VISION__MODEL`。

## 5. 边界约束

- NapCat 反向 WS 只连接 `hub-service`。
- MinIO bucket 不公开；agent 只看到 `object_key`。
- 第一版文件读取只支持文本类 MIME 或常见文本扩展名。
- 图片理解依赖独立 vision 配置，不复用 agent-service 的主模型配置。
