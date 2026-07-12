# aichan-qq-adapter

AICHAN 的 QQ 渠道适配器，基于 NapCat + OneBot v11。作为独立服务运行：对上通过 [Adapter Protocol v1](docs/adapter-protocol.md) 以 WebSocket 客户端连接 AICHAN 核心的 hub-service，对下提供反向 WS 入口供 NapCat 接入。

本仓库与 AICHAN 核心解耦，仅通过三条运行时契约耦合：共享的 external Docker 网络（`aichan-adapter-network`）、hub 服务名、以及双方一致的 adapter token。

## 职责

OneBot 私聊/群聊过滤、mention/block 规则、媒体 URL 与 file_id 解析、AICHAN XML 转换、QQ 消息及文件发送、用户资料/历史查询，以及 `face`、`mface`、`poke` 扩展。

## 接口

- `GET /healthz`
- `WS /onebot/v11/ws`：仅供 NapCat 连接。

## 部署

适配器与 NapCat 由本仓库的 `docker-compose.yml` 编排，并以 `external` 引用 AICHAN 核心 Compose 创建的 `aichan-adapter-network`。因此**必须先启动核心服务再启动适配器**，否则会因共享网络不存在而无法创建：

```bash
# 第一步：在 AICHAN 核心仓库根启动核心服务（创建共享网络）
docker compose up -d

# 第二步：在本仓库启动适配器与 NapCat
docker compose up -d
```

启动前复制 `.env.example` 为 `.env` 并配置 `ADAPTER__HUB_TOKEN`，其值须与核心侧 `.env` 中 `HUB__ADAPTER_TOKENS` 的 `qq:main` 令牌一致。NapCat 登录页在 http://localhost:6099/webui。

## 配置

配置位于 `config.yml`（白名单、require_mention、blocked_user_ids、NapCat 动作超时等，均由适配器自管），密钥经 `ADAPTER__HUB_TOKEN` 注入。配置 schema 和脱敏摘要会在注册时提交 hub。

QQ skill 位于 `skills/qq-channel/SKILL.md`。

## 文档

- [docs/aichan-qq-adapter.md](docs/aichan-qq-adapter.md) — 适配器实现说明
- [docs/adapter-protocol.md](docs/adapter-protocol.md) — 与 hub 之间的适配器协议 v1
