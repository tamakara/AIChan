# AIChan

AIChan 当前采用 **MCPHub + AgentRuntime** 的动态架构：

- 大脑通过 `MCPHub` 连接一个或多个 MCP Server，并动态发现可调用工具；
- 通道 MCP Server 在收到人类消息后仅发送 MCP 原生 `notifications/resources/updated` 唤醒信号（`uri=aichan://events/unread`）；
- 大脑侧 `AgentRuntime` 被唤醒后，第一步必须一次性调用全部 `*__fetch_unread_messages` 拉取未读；违反该约束会直接终止本轮推理。
- 大脑仅提供 async MCP 调用接口（`MCPManager` 已移除同步桥接方法）。
- 只要 MCP endpoint 发送资源更新信号，Hub 就会触发全局唤醒事件，并对 pending 重复信号执行 debounce。

> 本仓库已完成对旧静态插件模式的硬切换，不保留兼容链路。

## 核心组件

1. `aichan/mcp_hub`
   - `MCPManager`：统一管理 MCP Server 生命周期；
   - 动态发现 `mcp.types.Tool` 并以 async 方式包装为 LangChain `StructuredTool`。
2. `aichan/agent`
   - 基于 LangGraph 执行唤醒后的 Tool-as-Action 推理闭环。
3. `mcp_servers/cli`
   - CLI MCP Server，提供 `/mcp`（Streamable HTTP MCP 端点）与 `/v1/messages`、`/v1/events`（通道 API），并实现 `fetch_unread_messages` + 资源更新信号通知。

## 快速开始

### 1. 安装依赖

```bash
cd aichan
uv sync
```

### 2. 配置环境变量

必须提供：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_NAME`
- `LLM_TEMPERATURE`

可选：

- `MCP_SERVER_ENDPOINTS`（逗号分隔 MCP Streamable HTTP 端点）
  - 单端点：`http://localhost:9000/mcp`
  - 多端点：`http://localhost:9000/mcp,http://localhost:9100/mcp`
- `CLI_SERVER_HOST` / `CLI_SERVER_PORT`

### 3. 启动大脑

```bash
cd aichan
uv run python main.py
```

### 4. 启动 CLI MCP Server

```bash
cd mcp_servers
uv sync
uv run --package cli-mcp-server python -m cli.server
```

## 关键 API

- CLI 通道消息接口：
  - `GET /v1/messages?after_id=0`
  - `POST /v1/messages`
  - `GET /v1/events?after_id=0`
- MCP Streamable HTTP 端点：
  - `GET /mcp`
  - `POST /mcp`
  - `DELETE /mcp`

## 目录结构

```text
.
├─ aichan
│  ├─ main.py
│  ├─ mcp_hub
│  ├─ agent
│  ├─ core
│  └─ memory
├─ mcp_servers
│  └─ cli
└─ docs
```
