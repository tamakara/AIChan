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
  - 查询参数：
    - `start_line: int = 0`，0-based 起始行号
    - `line_count: int = 200`，最多返回多少行
  - 响应：
    - `user_id: str`
    - `content_markdown: str`
    - `start_line: int`
    - `line_count: int`
    - `total_lines: int`
    - `has_more: bool`
  - 语义：按原始 markdown 行读取用户长期记忆，不存在时返回空模板，不返回 `404`。超范围分页不报错，按切片语义返回空或剩余内容；只要切片非空，`content_markdown` 末尾补一个换行。

## 3. 存储结构

会话日志存到：

`root_dir/sessions/<url-encoded-session_id>.md`

用户记忆存到：

`root_dir/users/<url-encoded-user_id>.md`

`session_id` 和 `user_id` 都需要便于人工排查和定位，因此不做哈希。常见会话 ID 会直接落成 `private_123.md` / `group_456.md`，常见 QQ 数字 ID 会直接落成 `123.md`；包含 `/` 等路径保留字符的异常 ID 会做 URL segment 编码后再写入对应目录。

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
- session 无损日志每次 `/compress` 追加后都会按原始行数做容量控制；超过 `memory.session_max_lines` 时，直接删掉最旧前缀行，只保留最后 N 行。

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
| `memory.session_max_lines` | int | session 无损日志允许保留的最大原始行数，默认 `500` |

## 6. 故障语义

- session 读取失败：返回空字符串。
- user 记忆读取失败：返回空模板；分页元信息仍按空模板或当前切片结果计算。
- session 压缩失败：`/compress` 返回 500。
- user 内化失败：只记录日志，不影响 `/compress`。
