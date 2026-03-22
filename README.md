# AIChan

一个基于 `LangChain + LangGraph` 的模块化 AI 助手示例项目，采用 `uv workspace` 管理多包结构。  
当前提供命令行交互（CLI）、基础编排层、可插拔推理引擎和工具调用能力。

## 项目文档

- 项目结构详解：[docs/project-structure.md](docs/project-structure.md)
- 系统设计思路：[docs/system-design.md](docs/system-design.md)

## 架构概览

1. `peripherals`：外设层（I/O 总线），统一承载输入渠道与动作工具能力。
2. `synapse`：编排层，负责上下文拼接、队列调度与能力分发。
3. `brain`：推理层，基于 LangGraph 执行“推理 -> 调用能力 -> 再推理”。
4. `memory`：记忆扩展层（当前占位），后续承载长期/外部记忆能力扩展。
5. `core`：共享基础层，提供配置、日志、接口契约与数据模型。

结构细节与关键文件映射见：[docs/project-structure.md](docs/project-structure.md)。  
系统设计意图与演进思路见：[docs/system-design.md](docs/system-design.md)。

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置模型参数

服务启动入口在 `main.py`（接口定义在 `cli_server.py`）。请按你的实际环境确认：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL_NAME`
- `LLM_TEMPERATURE`

### 3. 分别启动服务端与客户端（两个终端）

```bash
# 终端 1：启动 AIChan 服务端
uv run python main.py

# 终端 2：启动独立 CLI 客户端
uv run python cli_client.py
```

两个进程都启动后即可对话，客户端按 `Ctrl+C` 退出。

## 目录结构

```text
.
├─ main.py
├─ cli_server.py
├─ cli_client.py
├─ pyproject.toml
├─ uv.lock
├─ docs
│  ├─ project-structure.md
│  └─ system-design.md
└─ packages
   ├─ core
   ├─ peripherals
   ├─ synapse
   ├─ brain
   └─ memory
```

## 常见自定义点

- 调整编排策略：`packages/synapse/src/synapse/agent.py`
- 替换推理流程：`packages/brain/src/brain/brain.py`
- 扩展记忆存取能力：`packages/memory/src/memory/`
- 扩展外设能力：`packages/peripherals/src/peripherals/channels/`、`packages/peripherals/src/peripherals/tools/`
