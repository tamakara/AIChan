# agent-service

`agent-service` 是 AIChan 的 HTTP API 子模块，基于 FastAPI 封装 `AgentCore`。

## 模块结构

- `agent_service/main.py`：模块根目录唯一启动入口。
- `agent_service/router/`：仅负责 HTTP 路由与请求/响应 Schema。
- `agent_service/app/app.py`：负责应用组装编排（AgentCore、依赖注入、FastAPI 应用拼装）。
- `agent_service/agent_core/`：核心 Agent 逻辑，不直接承担 HTTP 服务装配职责。
- `agent_service/prompts/system-prompt.md`：系统提示词，独立于运行时代码管理。

## API

- `GET /healthz`
- `POST /chat`

`POST /chat` 示例：

```json
{
  "user_input": "你好",
  "max_turns": 10
}
```

## 环境变量

- 默认值集中定义在仓库根目录 `.env.example`，`agent-service` 代码内不再保存任何环境变量默认值。
- `LLM_API_KEY`（必需）
- `LLM_BASE_URL`（必需）
- `MCP_GATEWAY_SSE_URL`（必需）
- `MCP_GATEWAY_AUTH_TOKEN`（必需；若不鉴权可显式设为空字符串）
- `LLM_MODEL_NAME`（必需）
- `HOST`（必需）
- `PORT`（必需）
- `LOG_LEVEL`（必需）

## 运行

本地运行（在仓库根目录）：

```bash
uv run --package agent-service agent-service
```

若使用本机直连 MCP Gateway，请将 `MCP_GATEWAY_SSE_URL` 改为 `http://localhost:9000/sse`。

容器运行入口：

```bash
agent-service
```
