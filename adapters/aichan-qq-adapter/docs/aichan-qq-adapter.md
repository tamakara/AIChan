# aichan-qq-adapter

AICHAN 的 QQ 渠道适配器，独立 FastAPI 服务，同时提供 NapCat 反向 WS 入口并作为 hub WebSocket 客户端运行。

职责包括：OneBot 私聊/群聊过滤、mention/block 规则、媒体 URL 和 file_id 解析、XML 转换、QQ 消息及文件发送、用户资料/历史查询，以及 `face`、`mface`、`poke` 扩展。

接口：

- `GET /healthz`
- `WS /onebot/v11/ws`：仅供 NapCat 连接。

配置位于本仓库根 `config.yml`。密钥使用 `ADAPTER__HUB_TOKEN`，白名单、require_mention、blocked_user_ids 和 NapCat 动作超时均由适配器自管。配置 schema 和脱敏摘要会在注册时提交 hub。

QQ skill 位于 `skills/qq-channel/SKILL.md`。

## 与核心的耦合面

作为独立仓库，本适配器与 AICHAN 核心只通过三条运行时契约耦合，不共享任何代码或构建上下文：

- **共享网络**：核心 Compose 创建的 `aichan-adapter-network`，本仓库以 `external` 引用。
- **hub 服务名**：`config.yml` 中 `hub_ws_url` / `hub_http_url` 指向核心网络内的 `hub-service`。
- **适配器令牌**：`ADAPTER__HUB_TOKEN` 须与核心侧 `HUB__ADAPTER_TOKENS` 的 `qq:main` 令牌一致。

适配器与 hub 之间的通信遵循 [Adapter Protocol v1](adapter-protocol.md)。

## 启动

适配器与 NapCat 由本仓库的 Compose 编排，并以 `external` 引用核心 Compose 创建的 `aichan-adapter-network`。因此**必须先启动核心服务再启动适配器**，否则会因共享网络不存在而无法创建：

```bash
# 第一步：在核心仓库根启动核心服务（创建共享网络）
docker compose up -d

# 第二步：在本仓库根启动适配器与 NapCat
docker compose up -d
```

启动前在本仓库根 `.env` 配置 `ADAPTER__HUB_TOKEN`，其值须与核心侧 `.env` 中 `HUB__ADAPTER_TOKENS` 的 `qq:main` 令牌一致。NapCat 登录页在 http://localhost:6099/webui。
