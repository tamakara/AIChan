# agent-service

## 1. 模块定位

`agent-service` 是 LLM 推理执行层：维护 `Session` 上下文、驱动多轮 LLM 推理与 MCP 工具调用，通过 HTTP 返回 AICHAN XML 回复。

不负责 QQ 消息接入、OneBot v11 解析与投递；这些职责由 `hub-service` 处理。

长期记忆由独立 `memory-service` 持久化。agent-service 每次运行前读取当前会话记忆并注入为 system message；压缩失败或读取失败只降级当前记忆能力，不阻断聊天。
记忆压缩采用进程内后台线程异步执行，请求返回不等待压缩完成；压缩成功后才会更新本地记忆层并裁剪对应旧记录。

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
如果 memory-service 可用，`<session ... />` 后会插入一条长期记忆 system message。新会话或空记忆使用固定占位文本；读取失败则不插入该消息。
群聊消息的 `<message>` 会携带 `user_id/nickname/at_bot`；`user_id` 是唯一身份，`nickname` 只用于称呼。
图片、视频和文件节点只携带 file-service 入库后的 `object_key`，agent 需要通过 MCP 工具 `image_describe` / `video_describe` / `file_read_text` 获取内容，不能根据文件名或消息文字猜测媒体内容。`<face name="...">` 和 `<mface summary="...">` 是用户表情语气信号，可用于理解情绪，但不等同于用户明确说出的文本。
当问题涉及用户偏好、长期习惯、历史承诺、项目背景、称呼方式或“之前说过/还记得”这类跨会话信息时，系统提示要求 agent 使用当前 `<message>` 或 `<session>` 中真实出现的 `user_id` 主动调用 `memory_get_user_memory`。群聊里只查询需要回复或被明确讨论的成员，避免把不同 `user_id` 的长期记忆混用。

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

`agent.py` 只在最终 `finish_reason == "stop"` 时检查回复是否为可解析的 XML。若本轮生成抛异常，或最终输出不是合法 XML，则不会把坏结果写入会话，而是按 `llm_max_retries` 预算重试同一轮生成；预算耗尽后统一返回固定 `<reply><text>...</text></reply>` 兜底文案。工具调用轮次本身不重放，因此不会因为 XML 校验失败重复执行工具。

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
- 当前自定义工具由 `tool-mcp-server` 提供：`qq_get_message_history`、`qq_get_user_info`、`file_get_metadata`、`file_read_text`、`memory_get_user_memory`、`image_describe`、`video_describe`
- `memory_get_user_memory` 由 agent 作为普通 MCP function tool 使用；工具结果会以 OpenAI tool 消息进入下一轮 LLM 输入，供最终回复引用。

### 2.5 对外消费（memory-service）

- `GET /api/v1/memories/{session_id}`：每次 `Agent.run()` 开始前读取最新 markdown 记忆
- `POST /api/v1/memories/{session_id}/compress`：当普通消息记录层条目数达到 `agent.memory_compress_every_n_records` 后，提交时间序日志文本（格式为 `[time] role: content`）
- 读取失败：清除当前会话 memory system message，本轮不注入记忆
- 压缩触发：正常回复提交后只负责异步投递后台压缩任务，不等待结果
- 压缩失败：保留普通消息记录层，不裁剪历史；后续新的聊天请求会再次检查阈值并重新投递

## 3. 核心数据模型

### 3.1 会话（`Session`）

- `session_id: str` — 会话标识
- `metadata: dict` — 创建时快照
- `_system_messages: Context` — 系统层，只包含初始 system prompt 和 `<session ... />`
- `_memory_message: Message | None` — 记忆层，只保留当前最新长期记忆 system message
- `_record_context: Context` — 记录层，保存 `<turn />`、user、assistant、tool 等会话过程消息
- `_record_entries: list[RecordEntry]` — 记录层对应的时间戳日志快照，供 memory 压缩使用
- `_compression_snapshot: MemoryCompressionSnapshot | None` — 当前后台压缩任务对应的冻结快照边界
- `_queued_user_messages: list[str]` — 运行中追加的新用户 XML 消息队列
- `_lock` — 线程锁，仅在修改 Context 时短暂持有

初始化时写入两条 system 消息：
- `SYSTEM_PROMPT`
- `<session session_id="..." max_turn="..." ... />`，包含 `session_id`、最大推理轮次，以及 metadata 中的 `platform/session_type/user_id|group_id/self_id`

memory 读取成功后会在系统层后插入或覆盖长期记忆 system message。最终发给 LLM 的输入固定按“系统层 → 记忆层 → 记录层 → 本轮 staged 输入”拼装。普通消息记录层会保留 `<turn />`、user、assistant、tool 消息；但提交给 memory-service 的快照文本会整理成带时间戳的逐行日志，并过滤掉 `<turn />` 这类纯结构分隔符。异步压缩进行中，旧记录仍继续保留在后续 LLM 输入里；压缩成功后只按快照边界裁掉旧前缀，保留压缩期间新增的记录和系统层、最新记忆层。

### 3.2 上下文（`Context`）

- `messages: list[Message]` — OpenAI Chat 消息历史
- `add_message(role, content, tool_calls, tool_call_id)` — 统一写入入口

### 3.3 Agent 执行循环

```
refresh memory markdown
pending_user_messages = [input_xml]
  → for turn in max_turns:
    → staged add_message("system", "<turn index=... />")
    → staged add_message("user") × pending_user_messages
    → generate with retry(system层 + memory层 + record层 + staged_messages)
    → if finish_reason == "stop":
        → drain queued_user_messages
        → if 有 queued:
            → pending_user_messages = queued
            → continue
        → else:
            → staged add_message("assistant")   # 只在最终 XML 合法且真正发送时提交
            → commit staged_messages
            → 若记录层条目数达到阈值，则异步投递普通消息记录层给 memory-service 压缩
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
- 每轮先写入 `<turn index="..."/>` system 消息，再写入本轮待处理 user messages；该 turn 消息会进入记录层，参与压缩阈值计数，但不会进入提交给 memory-service 的日志文本
- tool-call 分支先写入所有 tool result，queued user messages 延后到下一轮 `<turn>` 之后写入，保持 OpenAI tool-call 消息顺序合法
- stop 分支若发现 queued user messages，不提交当前 final reply，直接插入新 user 后继续推理
- 生成异常和最终 XML 非法统一视为“本轮生成失败”，按同一预算重试；预算耗尽后提交固定兜底回复
- memory 压缩只在正常成功回复后触发；fallback 回复属于失败收口，不会额外触发压缩
- 同一会话任意时刻最多只有一个后台压缩任务；压缩进行中不会重复投递
- `agent.memory_compress_every_n_records=10` 的 `10` 只统计记录层条目数，不包含初始 system prompt，也不包含长期记忆 system message

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
- `Agent.run()`：通用异常记录观测后返回固定 XML 兜底回复；最终 XML 非法也走同一条异常收口
- `Router.chat()`：统一捕获、记录日志、返回 HTTP 错误
- 工具调用失败：写入 `tool` 错误消息，不中断回合
- Langfuse 异常：降级吞掉，不中断主链路
- memory 读取失败：不注入记忆，不中断主链路
- memory 压缩失败：后台任务只清除 in-flight 状态，不裁剪历史，不中断主链路

## 5. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口 |
| `agent.model` | str | LLM 模型名 |
| `agent.max_turns` | int | 最大推理轮次 |
| `agent.temperature` | float | LLM 温度 |
| `agent.llm_timeout` | float | LLM 请求超时（秒） |
| `agent.llm_max_retries` | int | 统一生成失败重试次数；同时作用于 OpenAI SDK 请求重试和 agent 单轮生成重试，预算耗尽后返回固定兜底回复 |
| `agent.openai_api_key` | str | OpenAI 兼容 API Key |
| `agent.openai_base_url` | str | OpenAI 兼容 API 地址 |
| `agent.mcp_sse_url` | str | MCP SSE 网关地址 |
| `agent.mcp_auth_token` | str | MCP 鉴权令牌 |
| `agent.memory_enabled` | bool | 是否启用 memory-service |
| `agent.memory_base_url` | str | memory-service HTTP 地址 |
| `agent.memory_compress_every_n_records` | int | 记录层条目数达到多少后压缩一次，默认 `10`；只统计 `<turn />`、`user`、`assistant`、`tool` 等会话记录，不包含系统层和记忆层 |
| `agent.memory_timeout` | float | memory-service HTTP 请求超时（秒） |
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
- `llm_max_retries=3`：同时覆盖 SDK 请求失败与最终 XML 非法两类生成失败，统一重试后仍失败则返回固定兜底回复
- agent 只理解 AICHAN XML，不直接理解 OneBot v11 原始事件
- 长期记忆读取同步执行；压缩改为进程内后台线程异步执行，请求时延不再等待 memory-service 压缩返回

