# Adapter Protocol v1

## 传输与鉴权

适配器主动连接 `WS /api/v1/adapters/ws`，请求携带 Bearer Token。所有 JSON 信封包含 `version/type/id/correlation_id/payload`，`version` 固定为 `1.0`。首条消息必须是 `adapter.register`。

注册 payload 包含适配器/实例身份、配置 JSON Schema、脱敏配置摘要、capabilities、extensions 和 skills。`adapter_id:instance_id` 必须与 token 授权项一致；同实例新连接会替换旧连接。

## 消息类型

| 请求 | 响应 | 说明 |
|---|---|---|
| `adapter.register` | `adapter.registered` | 注册完整能力快照 |
| `heartbeat.ping` | `heartbeat.pong` | 连接保活 |
| `event.publish` | `event.ack` | 上报规范化 XML |
| `reply.deliver` | `reply.ack` | hub 投递 agent 回复 |
| `capability.invoke` | `capability.result` | 同轮查询适配器能力 |
| 任意 | `protocol.error` | 协议错误 |

event 和 command 使用稳定 ID。发送方等待 10 秒 ACK，最多尝试三次；接收方在进程内去重。媒体不走 WebSocket，统一使用 hub 的适配器文件 API。

语言无关信封 schema 位于 `protocol/adapter/v1/envelope.schema.json`。
