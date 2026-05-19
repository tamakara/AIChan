# channel-service

`channel-service` 是 AICHAN 的 QQ 协议适配层与 MCP 工具网关，负责：
- 与任意符合 OneBot v11 的实现通过单条反向 WebSocket 双向通信。
- 把入站 QQ 事件标准化后写入 Redis Streams（不保存会话状态）。
- 消费 `hub-service` 下发的动作消息并调用 OneBot action 执行。
- 暴露消息历史查询能力供 MCP Gateway / agent 调用。

## 设计目标

- 无状态网关：只做协议转换与队列投递，不维护会话业务状态。
- 单连接语义：OneBot v11 客户端仅连接 `WS /onebot/v11/ws`，事件与动作共用该连接。
- 队列解耦：与 `hub-service` 仅通过 Redis Streams 通信，消除服务直连耦合。

## 通信拓扑

- OneBot v11 客户端 <-> `channel-service`：`ws://channel-service:8010/onebot/v11/ws`
- `channel-service` -> Redis Stream `qq.events`：发布标准化事件
- Redis Stream `qq.actions` -> `channel-service`：消费动作并执行 OneBot action

## 运行日志

- 运行时已关闭 FastAPI/Uvicorn 与 `httpx/httpcore/websockets` 的框架日志，仅保留 `channel_service.*` 业务日志。
- 日志输出采用单轨可读格式：中文摘要 + 关键字段，不再输出 `event=...` 与全量结构化字段。
- 关键链路日志覆盖启动/停止、OneBot WS 连接状态、动作消费成功/丢弃/重试、OneBot action 调用成功/超时。

## 路由契约

- `GET /healthz`
  - 返回：`{"status":"ok"}`

- `WS /onebot/v11/ws`
  - OneBot v11 反向 WebSocket 连接入口。
  - 入站事件处理：仅文本消息进入事件链路；群聊仍在网关层忽略，私聊事件转为统一 JSON 后写入 `qq.events`。
  - 出站动作处理：动作消费者从 `qq.actions` 取到 `send_message` 后，通过该连接发送 OneBot action 并等待 `echo` 响应。

- `GET /api/v1/user/{user_id}/info`
  - 入参：`user_id=qq_123456`
  - 行为：转换为 `get_stranger_info` action，通过当前 OneBot 反向 WebSocket 连接下发。

- `GET /api/v1/message/history`
  - 入参：
    - `session_id=group_123|private_456`
    - `limit=1..50`
    - `before_message_id` 可选
  - 行为：
    - `group_*` -> `get_group_msg_history`
    - `private_*` -> `get_friend_msg_history`
    - 返回 `messages` 与 `next_before_message_id`

## Redis 消息契约

- 事件流：`qq.events`
  - 字段：`event_id`、`session_id`、`user_id`、`content`、`source`、`message_type`、`raw_event`、`created_at`

- 动作流：`qq.actions`
  - 字段：`action_id`、`session_id`、`action_type`、`payload`、`created_at`
  - v1 仅支持：`action_type=send_message`，`payload={"content":"..."}`

## MCP 工具契约

- 工具名：`qq_get_message_history`
  - 参数：
    - `session_id`：`group_123` 或 `private_456`
    - `limit`：`1..50`，默认 `20`
    - `before_message_id`：可选，正整数
  - 行为：
    - 工具参数校验通过后，调用本服务 HTTP 接口 `GET /api/v1/message/history`
    - 返回 MCP `tool result` 的 JSON 字符串，字段固定为：`session_id`、`messages`、`next_before_message_id`

## ID 映射规则

- 群会话：`group_id <-> session_id=group_{group_id}`
- 私聊会话：`user_id <-> session_id=private_{user_id}`
- 用户画像：`user_id <-> user_id=qq_{user_id}`

## 配置文件

配置文件路径：`channel-service/config.yml`

配置约束（与当前代码一致）：

- 仅从本服务目录内的 `config.yml` 读取运行配置。
- 不读取 `.env`、`.env.example`，也不支持任何环境变量别名。
- 修改地址、端口、超时、队列参数时，只更新 `channel-service/config.yml`。
- 在 Docker Compose 中通过只读挂载该配置文件，保证容器与本地运行共享同一配置语义。
- 配置加载阶段使用 Pydantic 严格校验：字段类型不匹配、缺失字段或出现未声明字段都会直接报错并阻断启动。

```yaml
server:
  host: 0.0.0.0
  port: 8010

adapter:
  onebot_ws_action_timeout_seconds: 5

redis:
  host: redis
  port: 6379
  db: 0
  password: ""
  events_stream: qq.events
  actions_stream: qq.actions
  actions_group: adapter-action-workers
  actions_consumer: channel-service-1
  actions_block_ms: 2000

mcp:
  base_url: http://channel-service:8010
  timeout_seconds: 5
```

消息历史查询与动作执行均依赖 OneBot v11 反向 WebSocket 已连接。

## 启动

在仓库根目录执行：

```bash
uv run --package channel-service channel-service
```

MCP stdio 入口（供 MCP Gateway 通过 `docker://` 拉起）：

```bash
uv run --package channel-service channel-mcp
```

Docker Compose 启动：

```bash
docker compose up -d --build channel-service
```

## 容器构建稳定性

- Dockerfile 改为在基础镜像内通过 `pip install uv==0.7.2` 安装 uv，避免依赖 `ghcr.io` 元数据拉取失败。
- `channel-service/Dockerfile` 已设置 `UV_HTTP_TIMEOUT=180` 与 `UV_HTTP_RETRIES=8`，降低网络抖动导致的依赖下载超时失败概率。
- `uv pip install --system .` 使用 3 次重试策略，针对 `uv_build` 元数据拉取偶发超时可自动恢复。

## MCP Gateway 接入

- Gateway 服务参数中增加 `docker://channel-service:latest`。
- `channel-service` 容器镜像默认入口为 `channel-mcp`（stdio MCP server）。
- Compose 中通过 `command: ["channel-service"]` 显式覆盖，保证业务 HTTP 服务与 MCP 工具容器职责分离。

## OneBot v11 反向 WS 手动对接

`channel-service` 仅要求上游实现满足 OneBot v11 事件与 action 响应字段约定，不绑定具体厂商实现（如 NapCat、LLOneBot 等）。

## 验证步骤

1. 健康检查：

```bash
curl http://localhost:8010/healthz
```

2. 在你的 OneBot v11 实现中配置反向 WebSocket Client：
   - 目标地址：`ws://channel-service:8010/onebot/v11/ws`
   - 事件消息需包含 `post_type` 字段。
   - action 响应需包含 `echo`、`status`、`retcode` 字段。
   - 为了兼容 NoneBot 解析，建议消息段格式使用 OneBot v11 常见 `array` 形态（如果实现支持该选项）。

3. 向机器人发送私聊消息，检查 Redis `qq.events` 是否出现新事件，随后检查 `qq.actions` 消费与回写日志。
