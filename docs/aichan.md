# AICHAN 系统总览

`core-service` 是唯一业务入口，负责 Adapter 长连接、事件防抖、会话串行、上下文和异步 Agent。`core-mcp-server` 只包装文件、长期记忆和视觉工具；Adapter capabilities 由 Core 根据在线 Manifest 直接生成会话级工具。

| 服务 | 容器端口 | 宿主端口 | 职责 |
|---|---:|---:|---|
| core-service | 8020 | 18020 | Adapter Protocol、上下文和 Agent |
| core-mcp-server | 8030 | 不暴露 | 内置 MCP 工具 |
| file-service | 8040 | 不暴露 | 文件元数据与 MinIO 对象 |
| memory-service | 8050 | 不暴露 | session/user 长期记忆 |
| MCP Gateway | 9000 | 不暴露 | 聚合内置及第三方 MCP |
| MinIO Console | 9001 | 19001 | 对象存储管理界面 |

Core 和适配器 Compose 共享 `aichan-adapter-network`。适配器必须使用 Protocol 2.0；v1 不再接受。所有会话、在线连接和 ACK 去重仍为进程内状态，重启后不补发未确认事件。

部署使用 `.env` 保存 Core、Memory、MinIO 与观测配置，`.env.mcp` 只保存 MCP Server 所需密钥，避免向持有 Docker Socket 的 Gateway 暴露全量凭据。

当前环境无法读取本机 Docker image digest，因此 Compose 暂时保留 MCP Gateway 与 MinIO 的 `latest` tag；部署到可访问 Docker API 的环境后，应先验证镜像再固定 digest，禁止猜测版本。
