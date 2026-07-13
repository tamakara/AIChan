# AICHAN 系统总览

`core-service` 是唯一业务入口，负责 Adapter 长连接、事件防抖、会话串行、上下文、异步 Agent 和内置工具。`memory-service` 保存 session 压缩日志与 user 长期记忆。

| 服务 | 容器端口 | 宿主端口 | 职责 |
|---|---:|---:|---|
| core-service | 8020 | 18020 | Adapter Protocol、Agent、文件感知与消息查询 |
| memory-service | 8050 | 不暴露 | session/user 长期记忆 |

Core Compose 不包含也不管理任何渠道适配器。Adapter 通过宿主机发布的 `18020` 端口或远程 Core URL 连接 Adapter Protocol，不依赖共享 Docker network 或容器服务名。文件不随事件上传：XML 只携带 Adapter file ref，Core 在 `file_perceive` 被调用时通过 Adapter HTTP 接口按需下载到 `/tmp/aichan-file-cache`。

所有配置统一放在 `.env` 与各服务 `config.yml`；系统不再使用 MinIO、SQLite 文件索引、MCP Gateway 或 MCP secrets 文件。
