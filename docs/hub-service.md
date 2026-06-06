# hub-service

## 1. 模块定位

`hub-service` 是 QQ 私聊会话编排中枢：通过唯一的 NapCat WebSocket 接收 OneBot v11 事件，按内部 `session_key` 做防抖合并与串行调度，调用 `agent-service` 生成 XML 回复，再通过同一条 NapCat WS 发送私聊消息。

OneBot v11 复杂性只停留在本服务边界。agent-service 不接收原始 OneBot 事件，也不直接输出 OneBot 消息段。

## 2. 接口契约

### 2.1 对外提供（HTTP）

- `GET /healthz`
  - 响应：`{"status":"ok"}`
- `GET /api/v1/user/{user_id}/info`
  - 通过 NapCat `get_stranger_info` 动作查询用户信息
- `GET /api/v1/message/history?message_type=private|group&peer_id=...`
  - 通过 NapCat 历史消息动作查询私聊或群聊记录，供 MCP 工具调用

### 2.2 对外消费（WebSocket）

- 连接 NapCat 反向 WS，接收 OneBot v11 事件
- 固定只处理 `post_type=message` 且 `message_type=private`
- `user_id` 必须存在于 `hub.allowed_user_ids`
- 白名单为空时全部忽略，不创建会话

### 2.3 对外消费（HTTP → agent-service）

- `POST {agent_url}/sessions` — 创建 agent 会话，metadata 包含 `platform/user_id/self_id`
- `POST {agent_url}/chat` — 发送 `<batch>` XML，接收 `<reply>` XML
- `POST {agent_url}/sessions/{session_id}/queue-message` — 同一会话运行中收到新消息时追加到 agent 会话队列

### 2.4 对外产出（WebSocket → NapCat）

- 通过 NapCat WS `send_action` 发送 `send_private_msg`
- `message` 由 `<reply>` 转换为 OneBot v11 消息段数组
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

### 3.3 XML 转换

- `onebot_private_events_to_input_xml(events)`：把防抖批次转换为 `<batch>`
- `reply_xml_to_onebot_segments(xml)`：把 `<reply>` 转换为 OneBot v11 私聊消息段
- 转换层丢弃 `raw_message`、`font`、群字段和无关 sender 字段

## 4. 防抖调度流程

```
事件到达 → 私聊 + 白名单过滤 → 入队 pending_events
  → 重置 debounce_deadline
  → 防抖静默窗口等待
  → 窗口内无新消息 → 提取批次到 inflight_events
  → 转换为 <batch>
  → POST /chat({input_xml})
  → 运行期间新消息：单条转换为 <batch> 并 POST /queue-message
  → 若 /chat 返回后发现运行期间曾 queue 新消息：丢弃旧回复
  → 重新等待防抖窗口，发送空 <batch /> 触发 agent 消化内部队列
  → 否则收到 {output_xml}
  → 转换为 OneBot 消息段并 send_private_msg
  → 仍有 pending → 重置窗口重跑
  → 无 pending → 会话空闲
```

关键规则：
- 非运行状态下，消息仍由 hub 的防抖窗口合并为一个 `<batch>` 后调用 `/chat`
- 正在运行时，同一会话新消息不进入 hub 的下一轮 pending 队列，而是立即调用 `/queue-message` 交给 agent 会话内部队列
- `/chat` 返回后、发送 QQ 回复前有本地 send gate；只要运行期间成功 queue 过新消息，旧回复就不发送
- send gate 丢弃旧回复后会重新等待完整防抖窗口，再用空 `<batch />` 触发 agent 继续运行并 drain queued messages

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

## 6. 设计权衡

- 会话状态全内存：不支持多副本和重启恢复
- 入口只支持 QQ 私聊，群聊作为后续独立入口再扩展
- 下游 HTTP `timeout=None`：避免误超时，但缺少硬超时保护
- 高频连发若持续未达静默窗口，会延后触发 agent
- NapCat WS 是单连接内存状态，当前部署目标是单实例
