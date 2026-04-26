# AIChan

一个基于 `uv workspace` 管理的多包项目。  
当前主运行模块为 `agent-service`（FastAPI + AgentCore）。

## 当前运行模式

- 根目录负责统一 `uv` 管理（依赖锁与唯一 `.venv`）。
- `agent-service` 作为子模块，提供 HTTP API 服务。
- 单实例 `AgentCore` 在服务启动时初始化并复用。

## 目录结构

```text
.
├─ pyproject.toml          # 根 workspace 配置
├─ uv.lock                 # 根依赖锁
├─ agent-service           # 子模块
│  ├─ pyproject.toml
│  ├─ Dockerfile
│  ├─ .env.example
│  └─ src/agent_service
└─ prompt_templates.py
```

## 快速开始

### 1. 安装依赖（根目录）

```bash
uv sync --all-packages
```

### 2. 启动 MCP 网关（本地部署前置）

本地部署前，先运行以下命令启动 MCP 网关：

```bash
docker mcp gateway run --transport sse --port 8080
```

启动后，从网关输出中获取并填写：

- `MCP_SSE_URL`
- `MCP_SSE_BEARER_TOKEN`

### 3. 配置环境变量

复制并编辑：

```bash
cp .env.example .env
```

至少需要配置：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `MCP_SSE_URL`
- `MCP_SSE_BEARER_TOKEN`

### 4. 启动服务

在根目录启动：

```bash
uv run --package agent-service agent-service
```

## API

- `GET /healthz`
- `POST /chat`
- `DELETE /session`

`POST /chat` 示例：

```json
{
  "user_input": "你好",
  "max_turns": 10
}
```

## Docker

在 `agent-service` 目录执行：

```bash
docker build -t agent-service-api:latest .
docker run --rm -p 8000:8000 \
  -e LLM_API_KEY=your_key \
  -e LLM_BASE_URL=https://api.openai.com/v1 \
  -e MCP_SSE_URL=http://your-mcp-gateway/sse \
  agent-service-api:latest
```
