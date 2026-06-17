# memory-service

## 1. 模块定位

`memory-service` 是 AICHAN 的会话长期记忆服务，按 `session_id` 维护独立 markdown 文件。它只负责读取、压缩和追加记忆，不参与 QQ 协议、不调用 MCP、不维护 agent 会话状态。

V1 采用“逐条 bullet 追加”的最小模型：不去重、不分类、不合并旧条目、不控制全文长度。

## 2. 接口契约

- `GET /healthz`
  - 响应：`{"status":"ok"}`

- `GET /api/v1/memories/{session_id}`
  - 响应：
    - `session_id: str`
    - `content_markdown: str`
  - 语义：不存在的会话返回空字符串，不返回 `404`，便于 agent-service 降级处理。

- `POST /api/v1/memories/{session_id}/compress`
  - 请求：
    - `messages_text: str`
  - 响应：
    - `session_id: str`
    - `content_markdown: str`
    - `added_markdown: str`
    - `added_count: int`
  - 语义：将一批普通消息记录整理成 markdown 日志 bullets 并追加到该会话文件末尾。要求尽量逐行保留时间、说话人和原始信息，只去掉无信息量的结构性文本。空白输入不调用 LLM，不追加内容，返回 `added_count=0`。

## 3. 存储与压缩

每个会话对应一个 markdown 文件，文件名为 `sha256(session_id).md`。`session_id` 来自外部服务，不能直接作为路径使用；hash 文件名用于隔离会话并避免路径逃逸。

压缩器使用 OpenAI-compatible Chat Completions 接口，固定要求输出：

- 每条一行 markdown bullet，按输入顺序保留日志时间线
- 若输入行带时间，输出必须保留原始时间，不改写、不推测
- 尽量一条输入事实对应一条输出日志，不把多条发言抽象成泛泛总结
- 保留说话人、原话关键表述、长期偏好、身份关系、明确事实、任务目标、约束、已确认结论、工具结果和后续上下文
- 只删除 <turn />、纯包装性的 XML 外壳、空行等无信息量结构文本；仍有事实或情绪的信息不能删

## 4. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口，默认 `8050` |
| `server.log_level` | str | 日志级别 |
| `memory.root_dir` | str | markdown 记忆文件根目录 |
| `memory.model` | str | 压缩用模型名 |
| `memory.openai_api_key` | str | OpenAI 兼容 API Key |
| `memory.openai_base_url` | str | OpenAI 兼容 API 地址 |
| `memory.llm_timeout` | float | LLM 请求超时（秒） |
| `memory.llm_max_retries` | int | OpenAI SDK 请求重试次数 |

当前环境变量：

| 环境变量 | 对应配置 | 必填 |
|----------|----------|------|
| `MEMORY__MODEL` | `memory.model` | 是 |
| `MEMORY__OPENAI_API_KEY` | `memory.openai_api_key` | 是 |
| `MEMORY__OPENAI_BASE_URL` | `memory.openai_base_url` | 否，Docker Compose 默认 `https://api.xiaomimimo.com/v1` |

## 5. 故障语义

- 读取失败由 agent-service 降级为“不注入记忆”。
- 压缩失败由 agent-service 降级为“不裁剪历史”。
- memory-service 自身在 LLM 压缩失败时返回错误，不吞掉异常。

