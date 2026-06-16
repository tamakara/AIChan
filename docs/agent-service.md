# agent-service

## 1. 模块定位

`agent-service` 是 LLM 推理执行层：维护 `Session` 上下文、驱动多轮 LLM 推理与 MCP 工具调用，通过 HTTP 返回 AICHAN XML 回复。

不负责 QQ 消息接入、OneBot v11 解析与投递；这些职责由 `hub-service` 处理。

## 2. 接口契约

### 2.1 对外提供（HTTP）

- `GET /healthz`
  - 响应：`{"status":"ok"}`

- `POST /sessions`
  - 请求（`CreateSessionRequest`）：
    - `session_id: str`（必填，hub-service 生成的 `private_<user_id>` 或 `group_<group_id>`）
    - `metadata: dict[str, Any]`（可选，默认 `{}`）
  - 响应（`CreateSessionResponse`）：
    - `session_id: str`
    - `metadata: dict[str, Any]`
  - 语义：每次调用创建指定 `session_id` 的新会话，不做幂等去重。
  - QQ 入口由 hub-service 传入 `platform/session_type/user_id|group_id/self_id`，agent-service 会写入 `<session session_id="..." max_turn="..." ... />` 系统消息。

- `DELETE /sessions/{session_id}`
  - 成功：`{"deleted": true}`
  - 失败：`404`（session 不存在）

- `POST /sessions/{session_id}/queue-message`
  - 请求（`QueueMessageRequest`）：
    - `input_xml: str`（必填，`<messages>` XML）
  - 成功：`{"queued": true}`
  - 失败：`404`（session 不存在）
  - 语义：同一会话运行中收到的新用户消息追加到 session 内部队列，等待 agent turn 边界插入。

- `POST /chat`
  - 请求（`ChatRequest`）：
    - `session_id: str`（必填）
    - `input_xml: str`（必填，`<messages>` XML）
  - 响应（`ChatResponse`）：
    - `output_xml: str`（`<reply>` XML）
  - 失败语义：
    - `session_id` 不存在：`404`
    - LLM/API/MCP 运行期异常：返回固定 `<reply><text>...</text></reply>` 兜底文案

### 2.2 LLM 输入输出格式

用户消息是 hub-service 生成的 `<messages>`：

```xml
<messages>
  <message id="999" time="1710000000" sub_type="friend" user_id="1" nickname="小明">
    <text>你好</text>
    <image object_key="xxx" name="abc.jpg" />
    <file object_key="xxx" name="note.txt" />
    <face name="微笑" />
    <mface emoji_package_id="1" emoji_id="abc" summary="商城笑脸" />
  </message>
</messages>
```

当前会话的 `session_id/platform/session_type/user_id|group_id/self_id` 和最大推理轮次会通过 `<session session_id="..." max_turn="..." ... />` system 消息提供。每轮推理还会写入一条 `<turn index="..."/>` system 消息，作为普通会话消息进入上下文。
群聊消息的 `<message>` 会携带 `user_id/nickname/at_bot`；`user_id` 是唯一身份，`nickname` 只用于称呼。
图片、视频和文件节点只携带 file-service 入库后的 `object_key`，agent 需要通过 MCP 工具 `image_describe` / `video_describe` / `file_read_text` 获取内容，不能根据文件名或消息文字猜测媒体内容。`<face name="...">` 和 `<mface summary="...">` 是用户表情语气信号，可用于理解情绪，但不等同于用户明确说出的文本。

LLM 最终回复必须是 `<reply>`，`<reply>` 下只能包含一个或多个 `<message>`，每个 `<message>` 会被组装成一条 QQ 消息：

```xml
<reply>
  <message>
    <text>笨蛋，找我有什么事喵？</text>
  </message>
</reply>
```

`<message>` 内可用节点为 `<text>`、`<face>`、`<image>`、`<file>`、`<record>`、`<video>`。文本和表情会组装成同一条 NapCat/OneBot 消息。`<face>` 与 `<text>` 并列即可，不需要嵌套在 `<text>` 内。文本中的 `<`、`>`、`&` 必须按 XML 规则转义。`object_key` 只能复用上下文或工具结果中真实出现过的对象，不能编造。

群聊多对象回复在 `<message>` 上加 `target_user_id`：

```xml
<reply>
  <message target_user_id="2" target_nickname="小红" at="true">
    <text>收到，笨蛋小红，我来总结喵。</text>
  </message>
</reply>
```

`agent.py` 中的 `_parse_agent_reply()` 负责把 LLM 输出收敛为 `<reply>`。若模型返回非法 XML 或非 `<reply>` 根节点，会包装为 `<reply><text>原始内容</text></reply>`。该逻辑只作为服务边界兜底，正常情况下应由系统提示词约束模型直接生成完整、闭合、可解析的 `<reply>`。

### 2.3 对外消费（LLM API）

- 客户端：`openai.OpenAI`
- 配置：`model` 由 `.env` 的 `AGENT__MODEL` 控制；`timeout`、`max_retries` 由 `config.yml` 的 `llm_timeout` / `llm_max_retries` 控制
- 请求参数：`model`、`messages`、`temperature`、`tool_choice="auto"`、`tools`
- 响应字段：`content`、`tool_calls`、`finish_reason`
- 错误处理：不在此层捕获，原始异常直接向上抛到 router

### 2.4 对外消费（MCP SSE）

- 启动阶段：`list_tools` 拉取并固化工具列表
- 运行阶段：`call_tool` 执行，返回 JSON 字符串写回 `tool` 消息
- 鉴权：`mcp_auth_token` 通过 `Authorization: Bearer` 发送
- 当前自定义工具由 `tool-mcp-server` 提供：`qq_get_message_history`、`qq_get_user_info`、`file_get_metadata`、`file_read_text`、`image_describe`、`video_describe`

## 3. 核心数据模型

### 3.1 会话（`Session`）

- `session_id: str` — 会话标识
- `metadata: dict` — 创建时快照
- `_context: Context` — 消息历史
- `_queued_user_messages: list[str]` — 运行中追加的新用户 XML 消息队列
- `_lock` — 线程锁，仅在修改 Context 时短暂持有

初始化时写入两条 system 消息：
- `SYSTEM_PROMPT`
- `<session session_id="..." max_turn="..." ... />`，包含 `session_id`、最大推理轮次，以及 metadata 中的 `platform/session_type/user_id|group_id/self_id`

### 3.2 上下文（`Context`）

- `messages: list[Message]` — OpenAI Chat 消息历史
- `add_message(role, content, tool_calls, tool_call_id)` — 统一写入入口

### 3.3 Agent 执行循环

```
pending_user_messages = [input_xml]
  → for turn in max_turns:
    → staged add_message("system", "<turn index=... />")
    → staged add_message("user") × pending_user_messages
    → LlmClient.generate(context.messages + staged_messages)
    → staged add_message("assistant")
    → if finish_reason == "stop":
        → drain queued_user_messages
        → if 有 queued:
            → 丢弃本轮 final assistant
            → pending_user_messages = queued
            → continue
        → else:
            → _parse_agent_reply()    # 收敛为 <reply>
            → commit staged_messages
            → finish_run_success()    # 上报观测
            → return AgentReply(output_xml)
    → if finish_reason == "tool_calls":
        → for each tool_call:
            → McpGateway.call_tool()
            → staged add_message("tool")
        → drain queued_user_messages
        → pending_user_messages = queued
    → else: raise
```

关键设计：
- LLM 调用期间不持锁；`/queue-message` 可以在运行中安全追加同会话用户消息
- 本轮 user/assistant/tool 消息先暂存在 staged messages，成功返回最终 `<reply>` 时一次性提交
- 每轮先写入 `<turn index="..."/>` system 消息，再写入本轮待处理 user messages；该 turn 消息会作为普通上下文持久化
- tool-call 分支先写入所有 tool result，queued user messages 延后到下一轮 `<turn>` 之后写入，保持 OpenAI tool-call 消息顺序合法
- stop 分支若发现 queued user messages，丢弃尚未发送的 final assistant，插入新 user 后继续推理
- 运行期异常记录观测后返回固定兜底回复，并提交本轮 user + fallback assistant，因为这条回复会实际发给用户

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
├── output: {output_xml}
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
- `Agent.run()`：通用异常记录观测后返回固定 XML 兜底回复
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
| `agent.llm_max_retries` | int | LLM 请求重试次数；当前配置为 3，全部失败后返回固定兜底回复 |
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

配置加载由 `pydantic-settings` 统一处理，优先级为：显式初始化参数 > 环境变量 > 根目录 `.env` > `agent-service/config.yml`。`config.yml` 只保留普通配置和空占位，模型名、Langfuse 地址与真实密钥通过 `AGENT__...` 嵌套环境变量覆盖。

`docker-compose.yml` 会读取根目录 `.env` 做变量插值，并通过 `agent-service.environment` 显式传递本服务需要的变量；`.env` 已被 Git 忽略，仓库只保留 `.env.example`。如果真实值曾经进入仓库，需要先在对应平台轮换。YAML 中 `key:` 会解析为 `null`，`key: ""` 会解析为空字符串；`agent.model` 和 `agent.openai_api_key` 都禁止为空，因此必须由环境变量提供有效值。

当前 agent-service 环境变量：

| 环境变量 | 对应配置 | 必填 |
|----------|----------|------|
| `AGENT__MODEL` | `agent.model` | 是 |
| `AGENT__OPENAI_API_KEY` | `agent.openai_api_key` | 是 |
| `AGENT__OPENAI_BASE_URL` | `agent.openai_base_url` | 否，Docker Compose 默认 `https://api.xiaomimimo.com/v1` |
| `AGENT__MCP_AUTH_TOKEN` | `agent.mcp_auth_token` | 否，默认空字符串 |
| `AGENT__LANGFUSE__HOST` | `agent.langfuse.host` | 是 |
| `AGENT__LANGFUSE__PUBLIC_KEY` | `agent.langfuse.public_key` | 启用 Langfuse 时必填 |
| `AGENT__LANGFUSE__SECRET_KEY` | `agent.langfuse.secret_key` | 启用 Langfuse 时必填 |

## 6. 设计权衡

- 会话全内存：不支持多副本和重启恢复
- `/sessions` 无回收机制：长期运行可能内存增长
- `llm_max_retries=3`：瞬时连接失败优先由 SDK 重试，全部失败后返回固定兜底回复
- agent 只理解 AICHAN XML，不直接理解 OneBot v11 原始事件
