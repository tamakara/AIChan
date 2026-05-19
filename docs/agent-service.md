# agent-service

`agent-service` 是 AIChan 的 HTTP API 子模块，基于 FastAPI 封装 `AgentCore`。

## 模块结构

- `agent_service/main.py`：模块根目录唯一启动入口。
- `agent_service/logger.py`：全局日志配置与统一 logger 获取入口。
- `agent_service/router/`：仅负责 HTTP 路由与请求/响应 Schema。
- `agent_service/app.py`：负责应用组装编排（AgentCore、依赖注入、FastAPI 应用拼装）。
- `agent_service/agent/`：核心 Agent 逻辑，不直接承担 HTTP 服务装配职责。
- `agent_service/prompts.py`：系统提示词，独立于运行时代码管理。

## API

- `GET /healthz`
- `POST /chat`

`POST /chat` 示例：

```json
{
  "session_id": "private_123",
  "user_message": "你好"
}
```

`max_turns` 由服务配置 `agent-service/config.yml` 中的 `agent.max_turns` 统一控制，不再支持按请求覆盖。

错误诊断：

- `/chat` 处理失败时会输出完整异常栈日志，并携带 `session_id`，用于快速定位会话级故障。

MCP 工具信息来源：

- `agent-service` 不直接维护工具清单；工具信息由 MCP Gateway 提供。
- 服务启动阶段会连接 `agent.mcp_sse_url`，通过 `list_tools` 拉取远端工具元数据（名称、描述、入参 schema）。
- 拉取到的工具信息会在进程内固化为当前运行时工具映射，并转换为 LLM `tools` schema 供后续推理使用。

运行日志：

- 运行时已关闭 FastAPI/Uvicorn 框架日志，仅保留 `agent_service.*` 自定义日志，避免框架访问日志干扰诊断。
- 日志输出采用“单轨可读格式”：只保留中文摘要与关键字段，不再输出 `event=...` 和全量 `key=value` 字段，优先保证排障阅读效率。
- 启动与请求链路会按事件类型输出最小必要字段（如会话号、轮次、耗时、工具名、状态），避免冗余信息淹没关键信号。
- 运行时同时抑制 `httpx/httpcore` 请求级 INFO 日志，避免第三方 HTTP 调用明细干扰业务日志主线。

## 配置文件

配置文件路径：`agent-service/config.yml`

配置约束（与当前代码一致）：

- 仅从本服务目录内的 `config.yml` 读取运行配置。
- 不读取 `.env`、`.env.example`，也不支持任何环境变量别名。
- 修改接口地址、端口、超时等参数时，只更新 `agent-service/config.yml`。
- 在 Docker Compose 中通过只读挂载该配置文件，保证容器与本地运行共享同一配置语义。
- 配置加载阶段使用 Pydantic 严格校验：字段类型不匹配、缺失字段或出现未声明字段都会直接报错并阻断启动。

```yaml
server:
  host: 0.0.0.0
  port: 8000

agent:
  model: gpt-5.5
  max_turns: 10
  openai_api_key: your_openai_api_key
  openai_base_url: https://api.openai.com/v1
  mcp_sse_url: http://mcp-gateway:9000/sse
  mcp_auth_token: ""
```

## 运行

本地运行（在仓库根目录）：

```bash
uv run --package agent-service agent-service
```

若使用本机直连 MCP Gateway，请将 `agent.mcp_sse_url` 改为 `http://localhost:9000/sse`。

容器运行入口：

```bash
agent-service
```

## 测试

`agent-service` 已补充基础单元测试，覆盖路由会话管理与 `AgentCore` 推理/工具调用边界行为。

测试文件：

- `agent-service/tests/test_router.py`
- `agent-service/tests/test_agent_core.py`

在仓库根目录执行：

```bash
uv run --package agent-service --extra test pytest agent-service/tests -q
```

## 容器构建稳定性

- Dockerfile 改为在基础镜像内通过 `pip install uv==0.7.2` 安装 uv，避免依赖 `ghcr.io` 元数据拉取失败。
- `agent-service/Dockerfile` 已设置 `UV_HTTP_TIMEOUT=180` 与 `UV_HTTP_RETRIES=8`，降低网络抖动导致的依赖下载超时失败概率。
- `uv pip install --system .` 使用 3 次重试策略，针对 `uv_build` 元数据拉取偶发超时可自动恢复。
