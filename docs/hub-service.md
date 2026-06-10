# hub-service

## 1. 模块定位

`hub-service` 是 QQ 私聊会话编排中枢：通过唯一的 NapCat WebSocket 接收 OneBot v11 事件，按内部 `session_key` 做防抖合并与串行调度，把 NapCat 媒体 URL 下载到 MinIO，调用 `agent-service` 生成 XML 回复，再通过同一条 NapCat WS 发送私聊消息。

OneBot v11 复杂性只停留在本服务边界。agent-service 不接收原始 OneBot 事件，也不直接输出 OneBot 消息段。

## 2. 接口契约

### 2.1 对外提供（HTTP）

- `GET /healthz`
  - 响应：`{"status":"ok"}`
- `GET /api/v1/user/{user_id}/info`
  - 通过 NapCat `get_stranger_info` 动作查询用户信息
- `GET /api/v1/message/history?message_type=private|group&peer_id=...`
  - 通过 NapCat 历史消息动作查询私聊或群聊记录，供 MCP 工具调用
- `GET /api/v1/files/{object_key:path}/metadata`
  - 返回已入库文件的 `object_key/name/mime/size/sha256`
- `GET /api/v1/files/{object_key:path}/content`
  - 返回原始 bytes，供图片理解工具读取
- `GET /api/v1/files/{object_key:path}/text?max_chars=12000`
  - 仅支持 `text/*` 或常见文本扩展名；非文本返回 422

### 2.2 对外消费（WebSocket）

- 连接 NapCat 反向 WS，接收 OneBot v11 事件
- 固定只处理 `post_type=message` 且 `message_type=private`
- `user_id` 必须存在于 `hub.allowed_user_ids`
- 白名单为空时全部忽略，不创建会话

### 2.3 对外消费（HTTP → agent-service）

- `POST {agent_url}/sessions` — 创建 agent 会话，metadata 包含 `platform/user_id/self_id`
- `POST {agent_url}/chat` — 发送 `<messages>` XML，接收 `<reply>` XML
- `POST {agent_url}/sessions/{session_id}/queue-message` — 同一会话运行中收到新消息时追加到 agent 会话队列

### 2.4 对外产出（WebSocket → NapCat）

- 通过 NapCat WS `send_action` 发送 `send_private_msg`
- `<reply>` 的每个直接子节点会按 XML 顺序独立发送：每个 `<text>`、`<image>`、`<record>`、`<video>`、`<face>` 都对应一次 `send_private_msg`
- `<image object_key="..." />`、`<record object_key="..." />`、`<video object_key="..." />` 会从 MinIO 读取 bytes，转换为 NapCat/OneBot v11 支持的 `base64://...` 后发送
- `<file object_key="..." />` 会从 MinIO 读取 bytes，并在原 XML 位置通过 NapCat `upload_private_file` 发送私聊文件
- `auto_escape` 固定为 `false`

## 3. 核心数据模型

### 3.1 会话键（`session_key`）

- 私聊：`private:<user_id>`
- 仅用于 hub-service 内部路由和回发目标，不传给 agent-service metadata

### 3.2 SessionRegistry

- `session_key → SessionRunner` 映射
- `session_key → agent_session_id` 映射
- 首次看到白名单内私聊用户：调用 `/sessions` 创建 agent 会话，再创建 runner
- 创建 agent 会话时传入：

```json
{
  "platform": "qq",
  "user_id": 123456,
  "self_id": 10001
}
```

### 3.3 媒体入库

- `MediaStorage.ensure_bucket()`：启动时确保 MinIO bucket 存在
- `MediaStorage.store_segment()`：下载带 `url` 的 `image/file/record/video` segment，计算 `sha256/size/mime/name` 并写入 MinIO
- `NapcatFileResolver`：当 `file` segment 没有 `url` 但带有 `file_id/file/id` 时，通过 NapCat `get_private_file_url` / `get_file` 尝试换取下载 URL，再交给 `MediaStorage` 入库
- object key 固定格式：`qq/private/{user_id}/{message_id}/{segment_index}-{sha256}.{ext}`
- `<messages>` 中只暴露 `object_key/name/mime/size/sha256`，不暴露 NapCat 原始 URL
- 无法换取下载 URL 的 `file` 输出 `<unsupported type="file" name="..." />`，保留文件名等安全元信息，避免 agent 完全丢失“用户发过文件”的语义

### 3.4 XML 转换

- `onebot_private_events_to_input_xml(events, media_storage)`：把防抖批次转换为 `<messages>`，需要 I/O 时会先完成媒体入库
- `reply_xml_to_onebot_segments(xml, media_storage)`：把 `<reply>` 转换为 OneBot v11 私聊消息段；出站图片/语音/视频 `object_key` 会在这里解析为 `base64://...`
- `reply_xml_to_file_uploads(xml, media_storage)`：把 `<file object_key="..." />` 转为 NapCat `upload_private_file` 参数
- `reply_xml_to_outbound_items(xml, media_storage)`：按 `<reply>` 直接子节点顺序生成出站动作项；hub-service 实际发送回复时使用该函数，避免文本和媒体合并后被 QQ 客户端吞掉部分展示
- 转换层丢弃 `raw_message`、`font`、群字段和无关 sender 字段

## 4. 防抖调度流程

```
事件到达 → 私聊 + 白名单过滤 → 入队 pending_events
  → 重置 debounce_deadline
  → 防抖静默窗口等待
  → 窗口内无新消息 → 提取批次到 inflight_events
  → 带 url 的媒体入库 MinIO；无 url 的 file 先尝试通过 NapCat file_id 换取下载 URL
  → 转换为 <messages>
  → POST /chat({input_xml})
  → 运行期间新消息：单条转换为 <messages> 并 POST /queue-message
  → agent-service 在同一轮推理内 drain queued messages 并收敛为最终 {output_xml}
  → 按 <reply> 子节点转换并逐条 send_private_msg / upload_private_file
  → 仍有 pending → 重置窗口重跑
  → 无 pending → 会话空闲
```

关键规则：
- 非运行状态下，消息仍由 hub 的防抖窗口合并为一个 `<messages>` 后调用 `/chat`
- 正在运行时，同一会话新消息不进入 hub 的下一轮 pending 队列，而是立即调用 `/queue-message` 交给 agent 会话内部队列
- hub 不再发送空 `<messages />` 触发补跑；运行中新消息是否覆盖旧回复由 agent-service 的 turn-loop 和 queued message drain 逻辑统一收口

## 5. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口 |
| `server.log_level` | str | 日志级别 |
| `hub.agent_url` | str | agent-service 地址 |
| `hub.debounce_seconds` | float | 防抖窗口（秒） |
| `hub.allowed_user_ids` | list[int] | 允许对话的 QQ 用户 ID；空数组表示全部忽略 |
| `napcat.ws_action_timeout_seconds` | int | NapCat 动作超时（秒） |
| `storage.endpoint` | str | MinIO S3 endpoint，compose 默认 `minio:9000` |
| `storage.bucket` | str | 媒体文件 bucket |
| `storage.access_key` | str | MinIO access key；通过 `STORAGE__ACCESS_KEY` 覆盖 |
| `storage.secret_key` | str | MinIO secret key；通过 `STORAGE__SECRET_KEY` 覆盖 |
| `storage.secure` | bool | 是否使用 HTTPS |
| `storage.download_timeout_seconds` | float | 下载 NapCat 媒体 URL 的超时秒数 |
| `storage.max_object_bytes` | int | 单个媒体对象最大字节数 |

配置加载由 `pydantic-settings` 统一处理，优先级为：显式初始化参数 > 环境变量 > 根目录 `.env` > `hub-service/config.yml`。内部 endpoint、bucket、timeout、大小限制固定维护在 `hub-service/config.yml`；`docker-compose.yml` 只额外传入 `STORAGE__ACCESS_KEY` / `STORAGE__SECRET_KEY`，默认复用 `.env` 中的 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`。

## 6. 设计权衡

- 会话状态全内存：不支持多副本和重启恢复
- 入口只支持 QQ 私聊，群聊作为后续独立入口再扩展
- 下游 HTTP `timeout=None`：避免误超时，但缺少硬超时保护
- 高频连发若持续未达静默窗口，会延后触发 agent
- NapCat WS 是单连接内存状态，当前部署目标是单实例
- 第一版文件读取只支持文本类；PDF/DOCX/OCR 抽取不在 hub-service 内实现
