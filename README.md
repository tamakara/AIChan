# AIChan

一个基于 `LangChain + LangGraph` 的模块化 AI 助手示例项目，采用 `uv workspace` 管理多包结构。  
当前默认运行模式为：

- `main.py` 启动 AIChan 核心（`NexusHub + Agent + Brain`）并内嵌启动 `FastAPI cli_server` 子线程。
- `cli_client.py` 是独立控制台客户端（纯标准库实现），可在其他位置单独运行，通过 HTTP 与 `cli_server` 通信。

消息存储与收发管理由 `cli_server` 负责。  
AIChan 侧 `CLIChannelPlugin` 每秒轮询一次未读状态（`/v1/status`），发现 AI 侧有未读后再向 `NexusHub` 推送信号。

## 项目文档

- 0号文档（边界说明）：[docs/0.boundary.md](docs/0.boundary.md)
- 1号文档（设计文档）：[docs/1.system-design.md](docs/1.system-design.md)
- 2号文档（架构文档）：[docs/2.project-structure.md](docs/2.project-structure.md)
- 3号文档（消息闭环）：[docs/3.message-loop.md](docs/3.message-loop.md)

## 架构概览

1. `plugins`：插件层（I/O 总线），统一承载输入渠道与动作工具能力。
2. `nexus`：中央神经枢纽，维护异步队列并驱动消费心跳。
3. `brain`：推理层，基于 LangGraph 执行“推理 -> 调用能力 -> 再推理”。
4. `cli_server`：独立双对象消息服务（`ai/user`），负责消息存储、未读状态维护与外部 API。
5. `cli_client`：独立用户端，负责控制台输入输出，通过 HTTP 与 `cli_server` 通信。
6. `core` / `memory`：共享能力与记忆扩展层。

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

至少需要配置：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_NAME`
- `LLM_TEMPERATURE`

CLI 通道服务固定监听本地地址：

- `http://127.0.0.1:8765`

### 3. 启动 AIChan 核心服务（含 cli_server）

```bash
uv run python main.py
```

### 4. 在另一个终端启动独立客户端

```bash
uv run python cli_client.py
```

启动后按提示输入要连接的服务地址（例如 `http://127.0.0.1:8765`）。

可选参数：

```bash
uv run python cli_client.py --poll-interval 0.2 --reply-timeout 8
```

## 目录结构

```text
.
├─ main.py
├─ cli_server.py
├─ cli_client.py
├─ pyproject.toml
├─ uv.lock
├─ docs
│  ├─ 0.boundary.md
│  ├─ 1.system-design.md
│  ├─ 2.project-structure.md
│  └─ 3.message-loop.md
└─ packages
   ├─ core
   ├─ plugins
   ├─ nexus
   ├─ brain
   └─ memory
```

## 常见自定义点

- 调整中枢队列与消费循环：`packages/nexus/src/nexus/hub.py`
- 替换推理流程：`packages/brain/src/brain/brain.py`
- 扩展记忆存取能力：`packages/memory/src/memory/`
- 扩展 HTTP 消息服务：`cli_server.py`
- 扩展外部协议映射与轮询触发策略：`packages/plugins/src/plugins/channels/cli.py`
