# hub-service

`hub-service` 是 AICHAN 的会话编排中枢，负责消费 `channel-service` 写入的提醒事件，按会话串行调度 `agent-service`，并把回复以动作消息写回队列。

## 设计目标

- 中枢编排：集中管理“提醒 -> agent -> 回复动作入队”主链路。
- 会话串行：同一 `session_id` 同一时刻仅运行一个 agent。
- 防抖合并：首轮触发采用 1 秒（可配置）防抖窗口，减少连续短消息的重复触发。
- 轻量状态：仅在内存维护会话状态，不做持久化恢复。

## 运行日志

- 运行时已关闭 FastAPI/Uvicorn 与 `httpx/httpcore/websockets` 的框架日志，仅保留 `hub_service.*` 业务日志。
- 日志输出采用单轨可读格式：中文摘要 + 关键字段，不再输出 `event=...` 与全量结构化字段。
- 关键链路日志覆盖启动/停止、事件消费与过滤、会话调度开始/成功/失败、调用 `agent-service` 与回复入队耗时。

## 路由契约

- `GET /healthz`
  - 返回：`{"status":"ok"}`

> `hub-service` 不再提供 `WS /qq/events` 事件入口；事件统一从 Redis Stream 消费。

## 队列契约与行为

- 事件输入流：`qq.events`（Consumer Group 消费）
  - 仅处理 `message_type=private`，群聊事件直接 ACK 丢弃。

- 动作输出流：`qq.actions`
  - 回复动作写入格式：`action_type=send_message`，`payload={"content":"..."}`。
  - 当前策略为“入队即成功”，不等待 `channel-service` 执行回执。

## 会话调度策略

- 会话状态：`running`、`pending_messages`、`debounce_deadline`、`debounce_task`（内存态）。
- 首条消息进入会话后，启动防抖窗口（默认 1 秒）；窗口内新消息会重置截止时间。
- 窗口到期后把 `pending_messages` 合并为一次 `user_message` 调用 `agent-service /chat`。
- 运行期间新消息只追加到 `pending_messages`，不打断当前轮。
- 当前轮结束后若有 pending，则重新进入“防抖 -> 下一轮”。

## 下游依赖接口

- `agent-service`
  - `POST /chat`
  - request: `{"session_id":"private_xxx","user_message":"..."}`
  - response: `{"reply":"..."}`

## 配置文件

配置文件路径：`hub-service/config.yml`

配置约束（与当前代码一致）：

- 仅从本服务目录内的 `config.yml` 读取运行配置。
- 不读取 `.env`、`.env.example`，也不支持任何环境变量别名。
- 修改地址、端口、防抖窗口、队列参数时，只更新 `hub-service/config.yml`。
- 在 Docker Compose 中通过只读挂载该配置文件，保证容器与本地运行共享同一配置语义。
- 配置加载阶段使用 Pydantic 严格校验：字段类型不匹配、缺失字段或出现未声明字段都会直接报错并阻断启动。

```yaml
server:
  host: 0.0.0.0
  port: 8020
  log_level: debug

hub:
  agent_url: http://agent-service:8000
  debounce_seconds: 1.0

redis:
  host: redis
  port: 6379
  db: 0
  password: ""
  events_stream: qq.events
  events_group: hub-event-workers
  events_consumer: hub-service-1
  events_block_ms: 2000
  actions_stream: qq.actions
```

## 启动

在仓库根目录执行：

```bash
uv run --package hub-service hub-service
```

Docker Compose 启动：

```bash
docker compose up -d --build hub-service
```

## 容器构建稳定性

- Dockerfile 改为在基础镜像内通过 `pip install uv==0.7.2` 安装 uv，避免依赖 `ghcr.io` 元数据拉取失败。
- `hub-service/Dockerfile` 已设置 `UV_HTTP_TIMEOUT=180` 与 `UV_HTTP_RETRIES=8`，降低网络抖动导致的依赖下载超时失败概率。
- `uv pip install --system .` 使用 3 次重试策略，针对 `uv_build` 元数据拉取偶发超时可自动恢复。
