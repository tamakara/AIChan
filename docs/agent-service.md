# agent-service

agent-service 维护 LLM 会话、工具循环、长期记忆和动态 runtime skills，不负责任何渠道连接或投递。

## HTTP API

- `POST /sessions`：创建会话，请求包含稳定 session_id 和 `adapter_id/instance_id/conversation_type/conversation_id/bot_id` metadata。创建前必须从 skill-service 成功解析一次 skill。
- `POST /chat`：输入 `<messages>`，返回严格的 `<reply><message>...</message></reply>`。
- `POST /sessions/{id}/queue-message`：运行中追入消息。
- `DELETE /sessions/{id}`。
- `GET /healthz`。

每轮推理动态组装基础规则、系统 skill、当前适配器 skill、session XML、长期记忆和历史记录。skill 刷新失败时保留会话最后成功快照；非法回复 XML 进入统一生成重试，耗尽后返回包含 `<message><text>` 的固定兜底。

新增配置：`agent.skill_base_url`、`agent.skill_timeout`。其余模型、MCP、记忆和 Langfuse 配置保持各自现有命名。
