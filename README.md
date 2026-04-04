# AIChan

AIChan 当前采用 **MCPHub + SignalHub** 的动态架构：

- 大脑通过 `MCPHub` 连接一个或多个 MCP Server，并动态发现可调用工具；
- `ChannelPollTrigger` 定时轮询通道消息并向 `SignalHub` 发送处理信号；
- `SignalProcessor` 串行消费信号，拉取增量消息、获取 MCP 工具快照并调用 Agent 推理回写。

> 本仓库已完成对旧静态插件模式的硬切换，不保留兼容链路。

## 核心组件

1. `aichan/mcp_hub`
   - `MCPManager`：统一管理 MCP Server 生命周期；
   - 动态发现 `mcp.types.Tool` 并包装为 LangChain `StructuredTool`。
2. `aichan/hub`
   - `SignalHub`：统一信号排队与顺序消费。
   - `ChannelPollTrigger`：轮询 `/v1/messages`，在新 user 消息出现时触发 `AgentSignal`。
   - `SignalProcessor`：基于通道配置拉取消息，并通过 MCPHub 获取工具驱动 Agent。
3. `aichan/agent`
   - 基于 LangGraph 执行推理与工具调用闭环。
4. `mcp_servers/cli`
   - CLI MCP Server，提供 `/mcp/sse`（MCP 隧道）与 `/v1/messages`、`/v1/events`（通道 API）。

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

- `MCP_SERVER_URLS`（逗号分隔 MCP SSE 地址，默认 `http://localhost:9000/mcp/sse`）
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
- MCP 工具隧道：
  - `GET /mcp/sse`
  - `POST /mcp/messages`

## 目录结构

```text
.
├─ aichan
│  ├─ main.py
│  ├─ mcp_hub
│  ├─ hub
│  ├─ agent
│  ├─ core
│  └─ memory
├─ mcp_servers
│  └─ cli
└─ docs
```
