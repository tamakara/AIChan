# memory-service

## 1. 模块定位

`memory-service` 负责两层记忆：

1. `session` 级无损压缩日志，供 `/api/v1/memories/{session_id}` 和 `/compress` 使用。
2. `user` 级内化记忆，按 `user_id` 单独存储为长期画像与相关记忆。

前者保留聊天记录的可追溯日志形态，后者是可检索的长期记忆，不要求逐字保真。

## 2. 接口契约

- `GET /healthz`
  - 响应：`{"status":"ok"}`

- `GET /api/v1/memories/{session_id}`
  - 响应：
    - `session_id: str`
    - `content_markdown: str`
  - 语义：读取 session 无损日志，不存在时返回空字符串。

- `POST /api/v1/memories/{session_id}/compress`
  - 请求：
    - `messages_text: str`
  - 响应：
    - `session_id: str`
    - `content_markdown: str`
    - `added_markdown: str`
    - `added_count: int`
  - 语义：同步返回 session 无损压缩结果；压缩成功后，服务会异步提炼用户级记忆，不阻塞该接口。

- `GET /api/v1/users/{user_id}/memory`
  - 响应：
    - `user_id: str`
    - `content_markdown: str`
  - 语义：读取用户长期记忆，不存在时返回空模板，不返回 `404`。

## 3. 存储结构

会话日志存到：

`root_dir/sessions/<sha256(session_id)>.md`

用户记忆存到：

`root_dir/users/<sha256(user_id)>.md`

`session_id` 和 `user_id` 都不直接进入路径，统一做 `sha256`，避免路径逃逸。

## 4. 压缩与内化

session 无损压缩 prompt 要求：

- 逐行保留信息
- 保留时间、说话人、对象、数字、约束、偏好、承诺、结论、工具结果
- 去掉只表示结构的文本
- 不要把原始聊天改写成摘要

用户内化 prompt 输出固定 markdown：

```md
## 用户画像

## 相关记忆
```

异步内化规则：

- `/compress` 成功后，从原始 `messages_text` 解析 `user_id="..."`。
- 同一批记录里出现多个 `user_id` 时，分别更新各自用户记忆。
- 每个用户更新都串行加锁，避免并发写入覆盖。
- 内化失败只记日志，不影响 `/compress` 响应，也不回滚 session 日志。

## 5. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | 监听地址 |
| `server.port` | int | 监听端口 |
| `server.log_level` | str | 日志级别 |
| `memory.root_dir` | str | markdown 记忆根目录 |
| `memory.model` | str | 压缩/内化模型名 |
| `memory.openai_api_key` | str | OpenAI 兼容 API Key |
| `memory.openai_base_url` | str | OpenAI 兼容 API 地址 |
| `memory.llm_timeout` | float | LLM 请求超时（秒） |
| `memory.llm_max_retries` | int | OpenAI SDK 重试次数 |

## 6. 故障语义

- session 读取失败：返回空字符串。
- user 记忆读取失败：返回空模板。
- session 压缩失败：`/compress` 返回 500。
- user 内化失败：只记录日志，不影响 `/compress`。
