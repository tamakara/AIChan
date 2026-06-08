# AICHAN

基于 OneBot v11 + LLM 的 QQ 机器人。NapCat 接入 → hub 编排与 QQ 动作出口 → agent 推理 → 回复透传。

## 架构

```
QQ 用户 ↔ NapCat ↔ hub-service ↔ agent-service ↔ MCP Gateway ↔ tool-mcp-server
              (WS)       (HTTP)         (SSE)             (MCP HTTP)
                         ↕
                       MinIO
```

## 快速开始

```bash
# 启动
docker compose up -d --build

# 扫码登录 QQ
# 打开 http://localhost:6099/webui，口令见 napcat/config/webui.json

# 查看日志
docker compose logs -f hub-service agent-service
```

宿主机访问端口：agent-service 为 `http://localhost:18000`，hub-service 为 `http://localhost:18020`。容器内服务地址仍保持 `agent-service:8000` / `hub-service:8020`。

## 配置

每个服务读取自己的 `config.yml`，Docker Compose 再用根目录 `.env` 注入模型、密钥、MinIO 和 vision 覆盖项。仓库中的密钥字段是占位值，首次启动前需要在本地填写真实值。

| 服务 | 配置 |
|------|------|
| agent-service | `agent-service/config.yml` |
| hub-service | `hub-service/config.yml` / MinIO 凭证环境变量 |
| tool-mcp-server | `tool-mcp-server/config.yml` / `VISION__...` |
| MinIO | `.env` 中的 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| NapCat | `napcat/config/*.json` |

## 文档

1. [docs/aichan.md](docs/aichan.md) — 系统总览
2. [docs/message-protocol.md](docs/message-protocol.md) — OneBot v11 消息协议
3. [docs/hub-service.md](docs/hub-service.md) — 会话编排
4. [docs/agent-service.md](docs/agent-service.md) — LLM 推理
5. [docs/tool-mcp-server.md](docs/tool-mcp-server.md) — QQ、文件与图片 MCP 工具
