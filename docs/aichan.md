# aichan

## 1. 系统定位

AICHAN 是一个基于 NapCat + OneBot v11 接入的 QQ 私聊助理系统：NapCat 接入 QQ 消息 → `hub-service` 做白名单、XML 转换、会话编排与 QQ 动作出口 → `agent-service` LLM 推理 → 回复回 QQ。

不依赖 Redis 等中间件，服务间直接通过 HTTP + WebSocket 通信。

## 2. 架构总览

```
用户 ↔ NapCat ↔ hub-service ↔ agent-service ↔ MCP Gateway ↔ napcat-mcp-server
                  (WS)         (HTTP)         (SSE)             (Docker MCP)
                       ↑                              │
                       └──── QQ 查询 HTTP API ◀───────┘
```

| 服务 | 职责 | 端口 |
|------|------|------|
| `napcat` | OneBot v11 QQ 客户端，收发消息 | 6099 (WebUI) |
| `napcat-mcp-server` | 将 QQ 查询能力包装为 MCP 工具，实际查询转发给 hub-service | 内部 |
| `hub-service` | 会话编排中枢：私聊白名单、防抖合并、XML 转换、调用 agent、统一持有 NapCat WS | 8020 |
| `agent-service` | LLM 推理执行：多轮对话、MCP 工具调用、AICHAN XML 回复生成 | 8000 |
| `mcp-gateway` | MCP 工具网关，聚合 playwright/fetch/time/napcat 工具 | 9000 |

## 3. 消息数据流

```
[QQ 用户发消息]
  → NapCat OneBot v11 WS 事件 → hub-service 接收
  → 私聊 + user_id 白名单过滤
  → 按 session_key 防抖合并多轮输入
  → OneBot v11 私聊事件转换为 <batch>
  → POST /chat → agent-service
  → Agent 多轮 LLM 推理 + MCP 工具调用
  → LLM 输出 <reply>
  → agent-service 返回 {output_xml}
  → hub-service 转换为 OneBot v11 消息段
  → NapCat WS send_action(send_private_msg)
  → QQ 用户收到回复
```

## 4. 接口契约

| 服务 | 端点 | 说明 |
|------|------|------|
| `agent-service` | `GET /healthz` | 存活探针 |
| `agent-service` | `POST /sessions` | 创建会话 |
| `agent-service` | `DELETE /sessions/{id}` | 删除会话 |
| `agent-service` | `POST /chat` | 发送 `<batch>`，返回 `<reply>` |
| `hub-service` | `GET /healthz` | 存活探针 |
| `hub-service` | `GET /api/v1/user/{id}/info` | QQ 用户信息查询，供 MCP 工具调用 |
| `hub-service` | `GET /api/v1/message/history` | QQ 历史消息查询，供 MCP 工具调用 |

### `/chat` 请求/响应格式

请求：
```json
{"session_id": "uuid", "input_xml": "<batch>...</batch>"}
```

响应：
```json
{"output_xml": "<reply><text>笨蛋，找我有什么事喵？</text></reply>"}
```

hub-service 将 `output_xml` 转为 OneBot v11 私聊消息段并发送给当前会话对应的 QQ 用户。

## 5. 配置

每个服务只读取各自目录下的 `config.yml`，不使用 `.env` 别名层。

提交到仓库的密钥字段只保留占位值。首次启动前需要在本地填写 `agent-service/config.yml` 的 OpenAI 兼容 API Key、Langfuse Key，以及 `napcat/config/webui.json` 的 WebUI token；如果这些值曾经提交过，必须先在对应平台轮换。

| 服务 | 配置文件 |
|------|----------|
| `agent-service` | `agent-service/config.yml` |
| `hub-service` | `hub-service/config.yml` |
| `napcat-mcp-server` | `napcat-mcp-server/config.yml` |
| `napcat` | `napcat/config/napcat.json` / `onebot11.json` / `webui.json` |

## 6. 快速开始

```bash
# 启动全套服务
docker compose up -d --build

# 扫码登录 QQ
# 打开 http://localhost:6099/webui，口令见 napcat/config/webui.json

# 验证日志
docker compose logs -f hub-service agent-service
```

宿主机访问端口避开 Windows 保留端口：`agent-service` 发布到 `18000`，`hub-service` 发布到 `18020`。容器内部仍使用原始端口 `8000` / `8020`，服务间配置无需改动。

## 7. 故障语义

| 故障 | 影响 |
|------|------|
| NapCat 断开 | 消息无法收发 |
| hub-service 故障 | 事件无法调度，回复无法发送 |
| agent-service 故障 | 无法生成回复，hub 返回 500 |
| MCP Gateway 故障 | agent 工具调用失败，但不影响不依赖工具的回复 |
| LLM API 故障（401/超时等） | agent 立即返回错误（60s 超时，0 重试） |

## 8. 设计权衡

- 会话状态在 `agent-service` 和 `hub-service` 的进程内存中，重启丢失，单实例部署
- 防抖窗口内合并消息，减少 LLM 调用次数
- NapCat 只有一条反向 WS 连接，由 `hub-service` 统一持有，避免收发链路和工具查询链路各自维护连接
- OneBot v11 复杂性收口在 `hub-service`，agent 只处理 AICHAN XML
- 错误只在最外层（router）记录，内层直接抛出
- 可观测性通过 Langfuse 上报，覆盖 LLM generation 和工具调用
