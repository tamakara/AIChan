# agent-service

## 1. 模块定位

`agent-service` 是 LLM 推理执行层：维护 `Session` 上下文、驱动多轮 LLM 推理与 MCP 工具调用，通过 HTTP 返回 OneBot v11 格式回复。

不负责消息接入与投递（由 `hub-service` 处理）。

## 2. 接口契约

### 2.1 对外提供（HTTP）

- `GET /healthz`
  - 响应：`{"status":"ok"}`

- `POST /sessions`
  - 请求（`CreateSessionRequest`）：
    - `metadata: dict[str, Any]`（可选，默认 `{}`）
  - 响应（`CreateSessionResponse`）：
    - `session_id: str`（服务端生成 UUIDv4）
    - `metadata: dict[str, Any]`
  - 语义：每次调用创建新会话，不做幂等去重。

- `DELETE /sessions/{session_id}`
  - 成功：`{"deleted": true}`
  - 失败：`404`（session 不存在）

- `POST /sessions/{session_id}/interrupt`
  - 成功：`{"interrupted": true}`
  - 失败：`404`（session 不存在）
  - 语义：由 hub-service 在同一会话运行中收到新消息时调用，用于停止旧 run 的后续写入。

- `POST /chat`
  - 请求（`ChatRequest`）：
    - `session_id: str`（必填）
    - `batch: str`（必填，OneBot v11 事件 JSON 数组字符串）
  - 响应（`ChatResponse`）：
    - `reply: str | list[dict]` — OneBot v11 回复内容，字符串会在 hub-service 投递前转为 `text` 段
    - `auto_escape: bool` — 是否转义 CQ 码，默认 `false`
  - 失败语义：
    - `session_id` 不存在：`404`
    - session 被显式中断：`409`
    - 运行期异常：`500`

### 2.2 LLM 输出格式

LLM 被指示直接输出完整的 OneBot v11 响应结构：

```json
{
  "reply": [{"type": "text", "data": {"text": "回复内容"}}],
  "auto_escape": false
}
```

`agent.py` 中的 `_parse_agent_reply()` 负责解析此格式，兼容以下情况：
- 标准数组 `[{...}]`
- LLM 误返回单对象 `{...}`（自动包装为数组）
- 纯文本 fallback（视为 `Message(text)`）

`auto_escape` 由 LLM 决定，不再硬编码。

### 2.3 对外消费（LLM API）

- 客户端：`openai.OpenAI`
- 配置：`timeout`、`max_retries` 由 `config.yml` 的 `llm_timeout` / `llm_max_retries` 控制
- 请求参数：`model`、`messages`、`temperature`、`tool_choice="auto"`、`tools`
- 响应字段：`content`、`tool_calls`、`finish_reason`
- 错误处理：不在此层捕获，原始异常直接向上抛到 router

### 2.4 对外消费（MCP SSE）

- 启动阶段：`list_tools` 拉取并固化工具列表
- 运行阶段：`call_tool` 执行，返回 JSON 字符串写回 `tool` 消息
- 鉴权：`mcp_auth_token` 通过 `Authorization: Bearer` 发送

## 3. 核心数据模型

### 3.1 会话（`Session`）

- `session_id: str` — 会话标识
- `metadata: dict` — 创建时快照
- `_context: Context` — 消息历史
- `_generation: int` — 用于抢占检测的版本号
- `_lock` — 线程锁，仅在修改 Context 时短暂持有

### 3.2 上下文（`Context`）

- `messages: list[Message]` — OpenAI Chat 消息历史
- `add_message(role, content, tool_calls, tool_call_id)` — 统一写入入口

### 3.3 Agent 执行循环

```
user message → add_message("user")
  → for turn in max_turns:
    → LlmClient.generate()        # LLM 调用（不持锁）
    → add_message("assistant")    # 锁内写入
    → if finish_reason == "stop":
        → _parse_agent_reply()    # 解析 OneBot v11 JSON
        → finish_run_success()    # 上报观测
        → return AgentReply(reply, auto_escape)
    → if finish_reason == "tool_calls":
        → for each tool_call:
            → McpGateway.call_tool()
            → add_message("tool")  # 锁内写入
    → else: raise
```

关键设计：
- LLM 调用期间不持锁；中断由 `/sessions/{id}/interrupt` 设置 generation 标记
- LLM 返回后检查本 run 是否被中断，被中断则抛 `SessionInterrupted`
- 错误只在内层抛出，router 统一 catch + log

### 3.4 LLM 客户端（`LlmClient`）

- 持有 `openai.OpenAI` 实例
- `generate(messages, tools_schema, temperature)` → `LlmResponse`
- 不带观测逻辑，不带错误处理，纯透传

### 3.5 可观测性（`Observability`）

- `NoopObservability`：关闭时启用，所有方法空实现
- `LangfuseObservability`：开启时启用
- 根 trace：`agent.chat.run`（chain 类型）
- 每轮 LLM 调用：generation span，记录 input/output/model/turn/duration
- 每次工具调用：tool span，name 为工具名，output 自动解析 JSON
- `finish_run_success/error`：合并 metadata（不覆盖 start_run 的初始字段）

Langfuse trace 结构：
```
agent.chat.run (chain)
├── metadata: {message_count, max_turns, run_id, status, duration_ms}
├── output: {reply, auto_escape}
├── agent.llm.generation (generation) × N
│   ├── input: context.messages
│   ├── output: {content, tool_calls, finish_reason}
│   └── metadata: {turn, duration_ms}
└── <tool_name> (tool) × N
    ├── input: tool_args
    ├── output: 结构化 JSON（自动解析）
    └── metadata: {turn, status, error, duration_ms}
```

## 4. 异常处理

- `LlmClient.generate()`：不捕获异常，直接向上抛
- `Agent.run()`：不捕获通用异常（除 `SessionInterrupted`），直接向上抛
- `Router.chat()`：统一捕获、记录日志、返回 HTTP 错误
- 工具调用失败：写入 `tool` 错误消息，不中断回合
- Langfuse 异常：降级吞掉，不中断主链路

## 5. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口 |
| `agent.model` | str | LLM 模型名 |
| `agent.max_turns` | int | 最大推理轮次 |
| `agent.temperature` | float | LLM 温度 |
| `agent.llm_timeout` | float | LLM 请求超时（秒） |
| `agent.llm_max_retries` | int | LLM 请求重试次数（建议 0，避免 401 等错误长时间等待） |
| `agent.openai_api_key` | str | OpenAI 兼容 API Key |
| `agent.openai_base_url` | str | OpenAI 兼容 API 地址 |
| `agent.mcp_sse_url` | str | MCP SSE 网关地址 |
| `agent.mcp_auth_token` | str | MCP 鉴权令牌 |
| `agent.langfuse.enabled` | bool | 是否启用 Langfuse |
| `agent.langfuse.host` | str | Langfuse 地址 |
| `agent.langfuse.public_key` | str | Langfuse 公钥 |
| `agent.langfuse.secret_key` | str | Langfuse 密钥 |
| `agent.langfuse.flush_at` | int | 批量上报阈值 |
| `agent.langfuse.flush_interval` | float | 上报间隔（秒） |
| `agent.langfuse.request_timeout` | float | Langfuse 请求超时（秒） |

密钥字段在仓库中只保留占位值。真实 `agent.openai_api_key`、`agent.langfuse.public_key`、`agent.langfuse.secret_key` 只应写入本地运行配置；如果真实值曾经进入仓库，需要先在对应平台轮换。

## 6. 设计权衡

- 会话全内存：不支持多副本和重启恢复
- `/sessions` 无回收机制：长期运行可能内存增长
- `llm_max_retries=0`：认证失败立即报错，不等待
- LLM 直接输出 OneBot v11 格式：全链路透传，观测一致
