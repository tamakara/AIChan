# hub-service

## 1. 模块定位

`hub-service` 是会话编排中枢：通过 NapCat WebSocket 接收 OneBot v11 事件，按 `session_key` 做防抖合并与串行调度，调用 `agent-service` 生成回复，再通过 NapCat WS 发送回复。

不负责 QQ 协议接入（由 NapCat 完成），不参与 LLM 推理（由 `agent-service` 完成）。

## 2. 接口契约

### 2.1 对外提供（HTTP）

- `GET /healthz`
  - 响应：`{"status":"ok"}`

### 2.2 对外消费（WebSocket）

- 连接 NapCat 反向 WS，接收 OneBot v11 事件
- 按 `allowed_message_types` 过滤（默认仅 `private`）
- 事件进入 `SessionRunner` 按 `session_key` 路由

### 2.3 对外消费（HTTP → agent-service）

- `POST {agent_url}/sessions` — 创建 agent 会话
- `POST {agent_url}/chat` — 发送消息批次，接收 OneBot v11 回复

### 2.4 对外产出（WebSocket → NapCat）

- 通过 NapCat WS `send_action` 发送 OneBot v11 动作：
  - `send_private_msg(user_id, message, auto_escape)`
  - `send_group_msg(group_id, message, auto_escape)`
- `message` 和 `auto_escape` 直接来自 agent-service 的 `reply` 和 `auto_escape` 字段

## 3. 核心数据模型

### 3.1 会话键（`session_key`）

- 私聊：`private:<user_id>`
- 群聊：`group:<group_id>`

### 3.2 SessionRunner

单个会话的运行器，核心状态：

| 状态 | 说明 |
|------|------|
| `pending_events` | 待处理事件队列 |
| `running` | 是否正在执行 agent 调用 |
| `debounce_deadline` | 防抖窗口截止时间 |
| `_lock` | 异步锁，保证串行 |

### 3.3 SessionRegistry

- `session_key → SessionRunner` 映射
- `session_key → agent_session_id` 映射
- 首次看到新 `session_key`：调用 `/sessions` 创建 agent 会话，再创建 runner
- 后续同会话复用同一 `agent_session_id`

## 4. 防抖调度流程

```
事件到达 → 入队 pending_events → 重置 debounce_deadline
  → 防抖静默窗口等待
  → 窗口内无新消息 → 提取批次
  → POST /chat（透传 OneBot v11 事件 JSON）
  → 收到 {reply, auto_escape}
  → send_action(send_msg, {message: reply, auto_escape})
  → 仍有 pending → 重置窗口重跑
  → 无 pending → 会话空闲
```

关键规则：
- 正在运行时新消息只入队不打断
- 运行结束后检查是否有新消息，有则重跑
- 重跑前重新等待完整防抖窗口

## 5. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口 |
| `server.log_level` | str | 日志级别 |
| `hub.agent_url` | str | agent-service 地址 |
| `hub.debounce_seconds` | float | 防抖窗口（秒） |
| `hub.allowed_message_types` | list[str] | 放行的消息类型（`private`/`group`） |
| `napcat.ws_action_timeout_seconds` | int | NapCat 动作超时（秒） |

## 6. 回复透传

hub-service 不修改 agent 返回的内容：

```
agent 返回: {reply: [...], auto_escape: false}
hub 透传:   send_msg({message: reply, auto_escape: auto_escape})
```

## 7. 设计权衡

- 会话状态全内存：不支持多副本和重启恢复
- 下游 HTTP `timeout=None`：避免误超时，但缺少硬超时保护
- 高频连发若持续未达静默窗口，会延后触发 agent
