# AIChan

AIChan 当前采用 **Registry + SignalHub** 的动态架构：

- 网关（如 `cli_gateway`）启动后主动向大脑注册；
- 大脑通过注册中心动态发现网关能力并映射为 LLM 可调用工具；
- 网关消息事件先进入全局事件总线，再由独立触发器推送到 `SignalHub`；
- `SignalProcessor` 串行消费信号，拉取增量消息并调用 Agent 推理回写。

> 本仓库已完成对旧静态插件模式的硬切换，不保留兼容链路。

## 核心组件

1. `aichan/registry`
   - 管理网关注册、OpenAPI 工具映射、SSE 感知接入。
2. `aichan/hub`
   - `SignalHub`：统一信号排队与顺序消费。
   - `RegistrySignalTrigger`：从 `global_event_bus` 转换为 `AgentSignal`。
   - `SignalProcessor`：基于 Registry 配置拉取消息、构建动态工具并驱动 Agent。
3. `aichan/agent`
   - 基于 LangGraph 执行推理与工具调用闭环。
4. `gateway/channels/cli`
   - CLI 通道网关，提供 `/v1/messages` 与 `/v1/events`，并在启动时自动注册到大脑。

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

- `AICHAN_REGISTRY_URL`（网关注册中心地址）
- `CLI_SERVER_HOST` / `CLI_SERVER_PORT`
- `CLI_GATEWAY_BASE_HOST`

### 3. 启动大脑

```bash
cd aichan
uv run python main.py
```

### 4. 启动 CLI 网关

```bash
python gateway/channels/cli/cli_gateway.py
```

## 关键 API

- 大脑注册接口：`POST /internal/registry/register`
  - 请求体：
    - `name: str`
    - `type: "channel" | "tool"`
    - `base_url: str`
    - `openapi_path: str`
    - `sse_path: str`（仅 `channel` 必填）
- CLI 网关消息接口：
  - `GET /v1/messages?after_id=0`
  - `POST /v1/messages`
  - `GET /v1/events?after_id=0`

## 目录结构

```text
.
├─ aichan
│  ├─ main.py
│  ├─ registry
│  ├─ hub
│  ├─ agent
│  ├─ core
│  └─ memory
├─ gateway
│  └─ channels
│     └─ cli
└─ docs
```
