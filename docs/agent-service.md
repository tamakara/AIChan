# agent-service

`agent-service` 是 AIChan 的 HTTP API 子模块，基于 FastAPI 封装 `AgentCore`。

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

- `LLM_API_KEY`（必需）
- `LLM_BASE_URL`（必需）
- `MCP_GATEWAY_SSE_URL`（必需）
- `MCP_GATEWAY_AUTH_TOKEN`（可选，默认空）
- `LLM_MODEL_NAME`（默认 `gpt-4.1-mini`）
- `HOST`（默认 `0.0.0.0`）
- `PORT`（默认 `8000`）
- `LOG_LEVEL`（默认 `info`）

## 运行

本地运行（在仓库根目录）：

```bash
uv run --package agent-service agent-service
```
