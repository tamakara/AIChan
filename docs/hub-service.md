# hub-service

## 定位

hub-service 是渠道无关的适配器连接与会话编排中枢，不包含 NapCat、OneBot、QQ 过滤、QQ 表情或渠道发送逻辑。

## 接口

- `WS /api/v1/adapters/ws`：Adapter Protocol v1，使用 `Authorization: Bearer <token>`。
- `GET /api/v1/adapters`：在线适配器、实例和能力摘要。
- `POST /api/v1/adapter/invoke`：按 session_id 调用其适配器能力。
- `POST /api/v1/adapter/files/from-url`：适配器媒体 URL 入库代理。
- `POST /api/v1/adapter/files`：multipart 文件上传代理。
- `GET /api/v1/adapter/files/{object_key}/metadata|content`：适配器读取媒体。
- `GET /healthz`。

适配器文件接口使用与 WebSocket 相同的 Bearer Token；hub 只代理 file-service，不解析渠道文件字段。

## 会话

session_id 为各段 URL 转义后的：

```text
adapter_id:instance_id:conversation_type:conversation_id
```

hub 对空闲消息做统一防抖；agent 运行中到达的新消息立即调用 queue-message。SessionRunner 空闲后可回收，但 session 路由和 agent 会话保持，后续消息不会重建并丢失上下文。

## 配置

`hub-service/config.yml` 定义 agent/file/skill 地址、防抖、ACK 和能力调用超时。`HUB__ADAPTER_TOKENS` 使用 JSON 对象覆盖授权表，例如 `{"qq:main":"secret"}`。适配器进程启停由部署系统负责。
