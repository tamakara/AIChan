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

默认值统一定义在根目录 `.env.example`，代码和 `docker-compose.yml` 不再内置回退默认值。

关键变量：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `MCP_GATEWAY_SSE_URL`
- `MCP_GATEWAY_AUTH_TOKEN`
- `LLM_MODEL_NAME`
- `HOST`
- `PORT`
- `LOG_LEVEL`
- `MCP_GATEWAY_PORT`
- `MCP_GATEWAY_SERVERS`

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

4. 本地直连运行前，将 `.env` 中 `MCP_GATEWAY_SSE_URL` 调整为 `http://localhost:9000/sse`。

5. 启动 agent-service（另一个终端）：

```bash
uv run --package agent-service agent-service
```

## Docker Compose 部署（推荐）

1. 从 `.env.example` 复制 `.env`，并按实际环境修改（至少替换 `LLM_API_KEY` 和 `MCP_GATEWAY_AUTH_TOKEN`）。
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
