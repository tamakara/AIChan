# AICHAN

基于 OneBot v11 + LLM 的 QQ 机器人。NapCat 接入 → hub 编排 → agent 推理 → 回复透传。

## 架构

```
QQ 用户 ↔ NapCat ↔ hub-service ↔ agent-service ↔ MCP Gateway
              (WS)       (HTTP)         (SSE)
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

## 配置

每个服务只读自己的 `config.yml`，不使用 `.env`。

| 服务 | 配置 |
|------|------|
| agent-service | `agent-service/config.yml` |
| hub-service | `hub-service/config.yml` |
| NapCat | `napcat/config/*.json` |

## 文档

1. [docs/aichan.md](docs/aichan.md) — 系统总览
2. [docs/message-protocol.md](docs/message-protocol.md) — OneBot v11 消息协议
3. [docs/hub-service.md](docs/hub-service.md) — 会话编排
4. [docs/agent-service.md](docs/agent-service.md) — LLM 推理
