# aichan

## 1. 系统定位

AICHAN 是一个基于 OneBot v11 协议的三层消息机器人系统：NapCat 接入 QQ 消息 → `hub-service` 会话编排 → `agent-service` LLM 推理 → 回复透传回 QQ。

不依赖 Redis 等中间件，服务间直接通过 HTTP + WebSocket 通信。

## 2. 架构总览

```
用户 ↔ NapCat ↔ hub-service ↔ agent-service ↔ MCP Gateway ↔ napcat-mcp-server
                  (WS)         (HTTP)         (SSE)             (Docker)
```

| 服务 | 职责 | 端口 |
|------|------|------|
| `napcat` | OneBot v11 QQ 客户端，收发消息 | 6099 (WebUI) |
| `napcat-mcp-server` | 提供 QQ 工具（历史消息等）供 agent 调用 | 8030 |
| `hub-service` | 会话编排中枢：防抖合并、调用 agent、透传回复 | 8020 |
| `agent-service` | LLM 推理执行：多轮对话、MCP 工具调用、OneBot v11 回复生成 | 8000 |
| `mcp-gateway` | MCP 工具网关，聚合 playwright/fetch/time/napcat 工具 | 9000 |

## 3. 消息数据流

```
[QQ 用户发消息]
  → NapCat OneBot v11 WS 事件 → hub-service 接收
  → 按 session_key 防抖合并多轮输入
  → POST /chat → agent-service
  → Agent 多轮 LLM 推理 + MCP 工具调用
  → LLM 直接输出 {"reply": [...], "auto_escape": false}
  → agent-service 透传返回
  → hub-service 解析 reply/auto_escape
  → NapCat WS send_action(send_msg, {message: reply, auto_escape})
  → QQ 用户收到回复
```

## 4. 接口契约

| 服务 | 端点 | 说明 |
|------|------|------|
| `agent-service` | `GET /healthz` | 存活探针 |
| `agent-service` | `POST /sessions` | 创建会话 |
| `agent-service` | `DELETE /sessions/{id}` | 删除会话 |
| `agent-service` | `POST /chat` | 发送消息，返回 OneBot v11 回复 |
| `hub-service` | `GET /healthz` | 存活探针 |

### `/chat` 请求/响应格式

请求：
```json
{"session_id": "uuid", "batch": "[{\"post_type\":\"message\",...}]"}
```

响应：
```json
{
  "reply": [{"type": "text", "data": {"text": "笨蛋，找我有什么事喵？"}}],
  "auto_escape": false
}
```

`reply` 为 OneBot v11 消息段数组，`auto_escape` 控制是否转义 CQ 码。hub-service 直接将这两个字段透传给 NapCat 的 `send_msg` 动作。

## 5. 配置

每个服务只读取各自目录下的 `config.yml`，不使用 `.env` 别名层。

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

## 7. 故障语义

| 故障 | 影响 |
|------|------|
| NapCat 断开 | 消息无法收发 |
| hub-service 故障 | 事件无法调度，回复无法发送 |
| agent-service 故障 | 无法生成回复，hub 返回 500 |
| MCP Gateway 故障 | agent 工具调用失败，但不影响纯文本回复 |
| LLM API 故障（401/超时等） | agent 立即返回错误（60s 超时，0 重试） |

## 8. 设计权衡

- 会话状态在 `agent-service` 和 `hub-service` 的进程内存中，重启丢失，单实例部署
- 防抖窗口内合并消息，减少 LLM 调用次数
- LLM 直接输出 OneBot v11 格式，全链路透传无转换
- 错误只在最外层（router）记录，内层直接抛出
- 可观测性通过 Langfuse 上报，覆盖 LLM generation 和工具调用
