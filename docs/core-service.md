# core-service

core-service 合并了原 Hub 与 Agent。外部只公开 `/healthz`、`/readyz`、`/api/v2/adapters/ws`、Adapter 状态和 Adapter 文件代理；不再提供 sessions/chat/queue-message HTTP API。

`ContextManager` 是会话状态唯一所有者。每轮模型上下文按 system.md、本地 skills、当前 Adapter skills、session XML、最后成功 memory、历史和暂存消息的顺序生成。固定提示词启动时加载；本地 skill 按文件指纹热更新，坏更新保留上一次成功快照；Adapter skill 每轮取当前在线 Manifest。

Agent、LLM、Memory、MCP 和 Adapter RPC 均为异步。单会话由 SessionRunner 串行，多会话可并发；运行中到达的新消息进入 ContextManager 队列，使旧最终回复失效。记忆压缩使用受管理的后台 task，同会话最多一个。

环境变量统一使用 `CORE__` 前缀。非密钥默认值位于 `core-service/config.yml`，固定提示词位于 `core-service/prompts/system.md`。
