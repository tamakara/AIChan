# AIChan

基于 `uv workspace` 的多包项目，当前核心服务是 `agent-service`（FastAPI + AgentCore）。

## 目录结构

```text
.
├─ pyproject.toml
├─ uv.lock
├─ .env.example
├─ docker-compose.yml
├─ docs/
│  └─ agent-service.md
└─ agent-service/
   ├─ pyproject.toml
   ├─ Dockerfile
   └─ src/agent_service
```

## 环境变量

必需变量：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `MCP_GATEWAY_SSE_URL`

常用变量：

- `MCP_GATEWAY_AUTH_TOKEN`（建议固定值；需与 MCP Gateway 一致）
- `LLM_MODEL_NAME`（默认 `gpt-4.1-mini`）
- `HOST`（默认 `0.0.0.0`）
- `PORT`（默认 `8000`）
- `LOG_LEVEL`（默认 `info`）

## 本地运行（uv）

1. 安装依赖（根目录）：

```bash
uv sync --all-packages
```

2. 复制环境变量文件并填写：

```bash
cp .env.example .env
```

3. 启动 MCP Gateway（示例为 PowerShell）：

```powershell
$env:MCP_GATEWAY_AUTH_TOKEN = "your_fixed_gateway_token"
docker mcp gateway run --transport sse --port 9000
```

4. 启动 agent-service（另一个终端）：

```bash
uv run --package agent-service agent-service
```

## Docker Compose 部署（推荐）

1. 配置 `.env`（至少设置 `LLM_API_KEY`、`LLM_BASE_URL`、`MCP_GATEWAY_AUTH_TOKEN`）。
2. 启动：

```bash
docker compose up -d --build
```

3. 验证：

```bash
curl http://localhost:8000/healthz
```

## API

- `GET /healthz`
- `POST /chat`

`POST /chat` 请求示例：

```json
{
  "user_input": "你好",
  "max_turns": 10
}
```

子模块文档请查看 `docs/agent-service.md`。
