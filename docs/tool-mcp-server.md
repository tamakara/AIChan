# tool-mcp-server

## 1. 模块定位

`tool-mcp-server` 是 AICHAN 自定义 MCP 工具层。它不直接连接 NapCat，不持有 MinIO 凭证；QQ 查询通过 HTTP 调用 `hub-service`，文件读取、图片理解和视频理解通过 HTTP 调用 `file-service`。

## 2. 启动方式

Compose 中的常驻 `tool-mcp-server` 容器直接运行 MCP 网络服务：

```bash
tool-mcp-mcp --transport streamable-http
```

MCP Gateway 通过 `tool-mcp-server/docker-mcp-catalog.yml` 中的 remote server 定义连接 `http://tool-mcp-server:8030/mcp`。这样 vision 的 `VISION__...` 环境变量会直接注入到常驻 `tool-mcp-server` service，而不是丢在 gateway 临时 `docker run` 的子容器外面。

## 3. MCP 工具

| 工具 | 说明 |
|------|------|
| `qq_get_message_history` | 查询私聊或群聊历史消息，调用 hub-service |
| `qq_get_user_info` | 查询用户信息，调用 hub-service |
| `file_get_metadata` | 根据 SHA-256 `object_key` 查询文件元数据，调用 file-service |
| `file_read_text` | 根据 SHA-256 `object_key` 读取文本类文件，非文本由 file-service 返回 422 |
| `image_describe` | 根据 SHA-256 `object_key` 读取图片 bytes，调用独立 vision 模型生成描述或回答问题 |
| `video_describe` | 根据 SHA-256 `object_key` 读取视频 bytes，抽取关键帧后调用独立 vision 模型生成描述或回答问题 |

`image_describe` 返回 JSON 字符串：

```json
{
  "type": "image_description",
  "object_key": "xxx",
  "mime": "image/jpeg",
  "description": "...",
  "question": "...",
  "answer": "..."
}
```

`video_describe` 返回 JSON 字符串：

```json
{
  "type": "video_description",
  "object_key": "xxx",
  "mime": "video/mp4",
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
| `mcp.qq_base_url` | str | hub-service HTTP API 地址，当前指向 `http://hub-service:8020` |
| `mcp.file_base_url` | str | file-service HTTP API 地址，当前指向 `http://file-service:8040` |
| `mcp.timeout_seconds` | float | 调用 hub-service/file-service 的超时秒数 |
| `vision.openai_base_url` | str | OpenAI 兼容 vision API 地址 |
| `vision.openai_api_key` | str | vision API Key |
| `vision.model` | str | vision 模型名 |
| `vision.timeout_seconds` | float | vision 请求超时秒数 |
| `vision.video_frame_count` | int | 视频理解抽帧数量，范围 1-12 |

配置加载由 `pydantic-settings` 统一处理，优先级为：显式初始化参数 > 环境变量 > 根目录 `.env` > `tool-mcp-server/config.yml`。内部 `mcp.qq_base_url`、`mcp.file_base_url` 和 timeout 固定维护在 `config.yml`；vision 把 key、base URL、模型名和视频抽帧数量放到环境变量，例如 `VISION__OPENAI_API_KEY`、`VISION__OPENAI_BASE_URL`、`VISION__MODEL`、`VISION__VIDEO_FRAME_COUNT`。

## 5. 边界约束

- NapCat 反向 WS 只连接 `hub-service`。
- MinIO bucket 不公开；tool-mcp-server 只通过 file-service 读取 SHA-256 `object_key`。
- 第一版文件读取只支持文本类 MIME 或常见文本扩展名。
- 图片/视频理解依赖独立 vision 配置，不复用 agent-service 的主模型配置。
- 视频理解通过 OpenCV 从视频 bytes 中按时间顺序抽取少量 JPEG 帧，再复用 vision LLM 的图片输入能力；当前不解析音频轨道。
