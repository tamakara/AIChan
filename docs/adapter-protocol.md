# Adapter Protocol 2.0

Adapter 使用 Bearer Token 主动连接 `WS /api/v2/adapters/ws`。Envelope 固定包含 `version/type/id/correlation_id/payload`，`version` 只能为 `2.0`，首包必须是 `adapter.register`。

注册 Manifest 必须包含 `adapter_id/instance_id/display_name/file_base_url`，并可声明配置摘要、skills、extensions 和 capabilities。`file_base_url` 必须是无 query/fragment 的 HTTP(S) 地址。

## 标准消息

| 请求 | 响应 | 说明 |
|---|---|---|
| `adapter.register` | `adapter.registered` | 注册在线 Manifest |
| `heartbeat.ping` | `heartbeat.pong` | 连接保活 |
| `event.publish` | `event.ack` | 上报实时 `messages_xml` |
| `reply.deliver` | `reply.ack` | 接收 `reply_xml` |
| `message.query` | `message.result` | 分页查询当前 conversation 历史 |
| `capability.invoke` | `capability.result` | 调用可选渠道专属能力 |

`message.query` 由 Core 写入稳定 session、conversation、opaque cursor 和 1–100 的 limit。Adapter 返回 `ok/messages_xml/next_cursor/has_more/error`；空结果使用 `<messages />`。查询结果必须与实时消息使用相同 XML v2 格式。

## 按需文件

Adapter 必须提供：

```text
GET {file_base_url}/{url-encoded file_ref}
Authorization: Bearer <Adapter Token>
```

响应 body 是原始文件，使用 `Content-Type`，可通过 `Content-Disposition` 提供文件名。Core 只在模型调用 `file_perceive` 时请求该接口。

Capability 是可选强类型扩展，由 JSON Schema 生成 `adapter__*` 工具；消息查询和文件获取不得重复声明为 capability。

JSON Schema 与示例位于 `protocol/adapter/v2`，不兼容 v1。
