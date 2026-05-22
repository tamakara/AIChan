# agent-service

## 1. 模块一句话定位
`agent-service` 是对话推理执行层：维护 `Agent` 上下文、驱动 LLM 多轮推理与 MCP 工具调用，并通过 HTTP 接口返回回复。  
不负责消息接入与投递（由 `adapter-service` / `hub-service` 处理）。

## 2. 接口契约
### 2.1 对外提供（HTTP）
- `GET /healthz`
  - 响应：`{"status":"ok"}`

- `POST /agents`
  - 请求体（`CreateAgentRequest`）：
    - `metadata: dict[str, Any]`（可选，默认 `{}`）
  - 响应体（`CreateAgentResponse`）：
    - `agent_id: str`（服务端生成 UUIDv4）
    - `metadata: dict[str, Any]`（原样返回）
  - 语义：
    - 每次调用都创建新的 `Agent`（不做幂等去重）。
    - 创建时即注入 `SYSTEM_PROMPT` 与一次性 `<session_start ...>` 上下文头。

- `POST /chat`
  - 请求体（`ChatRequest`）：
    - `agent_id: str`（必填，必须已创建）
    - `messages: list[ChatMessage]`（最少 1 条）
    - `message_mode: "start" | "append"`（可选，默认 `"start"`）
    - `ChatMessage` 固定字段：
      - `user_id: str`
      - `event_time: str`
      - `content: str`
  - 响应体（`ChatResponse`）：
    - `reply: str`
  - 处理语义：
    - 严格先创建后聊天：`agent_id` 不存在时直接返回 `404`。
    - 路由入口先把消息列表渲染为 XML，再作为一次 `user` 输入交给 `Agent`。
    - 统一使用 `<messages mode="...">...</messages>` 包裹消息。
    - `message_mode="start"` 时渲染为 `<messages mode="start">`，`message_mode="append"` 时渲染为 `<messages mode="append">`。
    - 包裹内使用 `<message user_id="..." event_time="...">文本内容</message>` 片段，按输入顺序保留，属性和值统一做 XML 转义。
    - 会话级标识（`session_id`、`agent_id`）只在创建 `Agent` 时通过 `<session_start ...>` 注入，不在每轮消息体重复携带。
    - 同一 `agent_id` 串行执行，不同 `agent_id` 可并行。
  - 失败语义：
    - `agent_id` 不存在：`404`，`detail=agent not found`
    - 运行期未捕获异常：`500`，`detail` 为异常字符串

### 2.2 对外消费（LLM API）
- 客户端：`openai.OpenAI`
- 请求参数（`chat.completions.create`）：
  - `model`
  - `messages`（`Agent` 累积上下文）
  - `temperature`
  - `tool_choice="auto"`
  - `tools`（来自 MCP 注册结果）
- 响应关键字段：
  - `content`
  - `tool_calls`
  - `finish_reason`（`stop/length/tool_calls/content_filter/function_call`）
- 错误语义：
  - `APIStatusError`：记录状态码与响应体后抛 `RuntimeError`
  - 其他异常：记录异常后抛 `RuntimeError`

### 2.3 对外消费（MCP SSE）
- 启动阶段：调用 `list_tools` 拉取远端工具列表并本地固化。
- 运行阶段：按工具名调用 `call_tool`，返回 JSON 字符串写回 `tool` 消息。
- 鉴权：如配置了 `mcp_auth_token`，通过 `Authorization: Bearer <token>` 发送。

## 3. 核心数据模型
### 3.1 运行上下文模型（`Agent`）
- `agent_id`：上下文隔离标识（由服务端创建）。
- `metadata`：创建时写入并冻结快照（只读暴露）。
- 初始化时固定注入：
  - `system`: `SYSTEM_PROMPT`
  - `system`: `<session_start agent_id="..." ...>`
  - `session_start` 标签由 `services/tag_builder.py::build_session_start_tag` 统一构建
- 后续每次 `run`：
  - 通过 `Context.add_message` 追加 `user`（XML 文本）
  - 由 `Agent` 负责多轮循环、工具调用与观测埋点
  - 每轮直接调用 `LlmClient.generate` 获取模型输出
  - `Agent` 统一把 `assistant/tool` 写回 `Context`

### 3.2 会话上下文模型（`Context`）
- `messages: list[Message]`：OpenAI Chat 消息历史。
- `add_message(...)`：统一封装 `assistant.tool_calls` 与 `tool.tool_call_id` 的写入规则。
- 设计目标：把“长期上下文写入”职责收口在 `Agent + Context`，避免多处写入导致并发与重复消息问题。
- 消息 XML 标签由 `services/tag_builder.py::render_messages_xml/build_message_tag` 统一构建与转义（含 `messages mode="..."` 顶层包裹）。

### 3.3 会话运行注册表（`AgentRegistry`）
- 结构：`dict[agent_id, Agent]`
- 语义：
  - `create(metadata)`：总是生成新 UUIDv4 并注册
  - `get(agent_id)`：命中返回 `Agent`，否则 `None`

### 3.4 LLM 响应模型（`LlmResponse`）
- `content: str`
- `tool_calls: List[ToolCall]`
- `finish_reason`：控制状态机分支的关键字段

### 3.5 可观测性模型（`Observability`）
- `NoopObservability`：关闭观测时启用，所有方法空实现。
- `LangfuseObservability`：开启观测时启用，统一封装 trace/generation/tool span 上报。
- 根 trace 名称固定：`agent.chat.run`。
- 根 trace metadata 固定包含：`agent_id`、`message_count`、`max_turns`、`run_id`、`agent_metadata`。

## 4. 核心业务流程
```mermaid
flowchart TD
    A[POST /agents] --> B[创建 Agent]
    B --> C[注入 SYSTEM_PROMPT]
    C --> D[注入 session_start]
    D --> E[返回 agent_id]

    F[POST /chat] --> G{agent_id 存在?}
    G -->|否| H[返回 404]
    G -->|是| I[messages 渲染 XML]
    I --> J[Agent.run]
    J --> K[追加 user(XML)]
    K --> L[LlmClient.generate]
    L --> M[LLM stop?]
    M -->|是| N[返回 reply]
    M -->|tool_calls| O[执行 MCP 工具并回写 tool 消息]
    O --> L
```

## 5. 配置项与运行依赖
### 5.1 配置文件
- 路径：`agent-service/config.yml`
- 加载方式：仅 YAML；Pydantic 严格校验（`extra="forbid"`）。

### 5.2 配置项（当前代码）
- `server.host`、`server.port`
- `agent.model`
- `agent.max_turns`
- `agent.temperature`
- `agent.openai_api_key`
- `agent.openai_base_url`
- `agent.mcp_sse_url`
- `agent.mcp_auth_token`
- `agent.langfuse.enabled`
- `agent.langfuse.host`
- `agent.langfuse.public_key`
- `agent.langfuse.secret_key`
- `agent.langfuse.flush_at`
- `agent.langfuse.flush_interval`
- `agent.langfuse.request_timeout`

### 5.3 运行依赖
- OpenAI 兼容 Chat Completions API
- MCP SSE Gateway（工具列表与工具调用）
- FastAPI / uvicorn / anyio / mcp-python SDK

## 6. 非功能性设计
### 6.1 错误处理
- 路由层在 `/chat` 维持统一异常边界：未知异常统一 `500`。
- 工具调用失败不会中断回合，而是写入 `tool` 错误消息交给模型决定后续策略。
- Langfuse SDK 异常统一降级吞掉，仅记录本地日志，不中断主链路回复。

### 6.2 日志
- 统一前缀：`agent_service.*`
- 关键事件：`agent_created`、`chat_received`、`chat_completed`、`chat_failed`、`agent.run_*`
- 关键字段：`agent_id`、`message_count`、`message_len`、`reply_len`、`elapsed_ms`

### 6.3 Langfuse 观测语义
- 每次 `/chat` 对应一个 root trace（`agent.chat.run`）。
- 每轮 LLM 调用记录 generation：输入为完整 `context.messages`，输出包含 `content/tool_calls/finish_reason`。
- 每次 MCP 工具调用记录 tool span：`tool_name`、`tool_args`、`status`、`error`、`duration_ms`。
- `Agent` 成功/失败时分别写 root trace 终态，并在应用 shutdown 阶段执行一次带超时保护的 `flush`。
- 当前仅覆盖 `agent-service` 内部观测，不跨 `hub-service` / `adapter-service` 透传 trace id。

## 7. 设计权衡与已知不足
- `Agent` 状态仅存内存：实现简单，但不支持跨实例共享与重启恢复。
- `/agents` 每次都新建：调用链最清晰，但没有去重/回收机制，长期运行可能增长。
- `/chat` 严格 404 语义：契约清晰，但 hub 必须保证先创建再聊天。

