# Adapter Protocol 2.0

适配器使用 Bearer Token 主动连接 `WS /api/v2/adapters/ws`。Envelope 固定包含 `version/type/id/correlation_id/payload`，其中 `version` 只能为 `2.0`，首包必须是 `adapter.register`。

注册 Manifest 包含身份、配置摘要、capabilities、extensions 和 Markdown skills。Capability 的 JSON Schema 会直接生成 `adapter__*` 会话工具，并用于调用前后的输入输出校验。Extension 使用点分类型名和仅含标量属性的 object schema。

| 请求 | 响应 | 说明 |
|---|---|---|
| `adapter.register` | `adapter.registered` | 注册完整在线 Manifest |
| `heartbeat.ping` | `heartbeat.pong` | 连接保活 |
| `event.publish` | `event.ack` | 通过 `messages_xml` 上报 XML v2 |
| `reply.deliver` | `reply.ack` | 通过 `reply_xml` 接收回复 |
| `capability.invoke` | `capability.result` | 调用当前适配器强类型能力 |

事件和命令使用稳定 ID。ACK 默认等待 10 秒、最多三次；接收端在当前进程内去重。媒体通过 `/api/v2/adapter/files/...` 入库或读取，不在 WebSocket 中传输二进制。

JSON Schema 和示例位于 `protocol/adapter/v2`。本次升级不兼容 v1。
