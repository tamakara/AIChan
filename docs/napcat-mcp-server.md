# napcat-mcp-server

## 1. 模块定位

`napcat-mcp-server` 是 QQ 查询能力的 MCP 包装层。它不直接连接 NapCat，不持有 WebSocket；MCP 工具请求会通过 HTTP 调用 `hub-service` 的 QQ 查询 API，由 hub-service 复用唯一 NapCat WS 执行动作。

## 2. 启动方式

镜像通过 Docker label 暴露 MCP 命令：

```bash
napcat-mcp-mcp
```

`docker compose` 中保留 `napcat-mcp-server` 服务用于构建并运行轻量 HTTP 进程；MCP Gateway 使用 `docker://napcat-mcp-server:latest` 时会按镜像 label 启动 MCP 命令。

## 3. MCP 工具

| 工具 | 说明 |
|------|------|
| `qq_get_message_history` | 查询私聊或群聊历史消息 |
| `qq_get_user_info` | 查询用户信息 |

## 4. 配置项

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `server.host` | str | HTTP 占位服务监听地址 |
| `server.port` | int | HTTP 占位服务监听端口 |
| `mcp.base_url` | str | QQ 查询 HTTP API 地址，当前指向 `http://hub-service:8020` |
| `mcp.timeout_seconds` | float | 调用 hub-service 的超时秒数 |

配置加载由 `pydantic-settings` 统一处理，优先级为：显式初始化参数 > 环境变量 > 根目录 `.env` > `napcat-mcp-server/config.yml`。当前 napcat-mcp-server 的配置均为非敏感拓扑与超时参数，默认直接维护在 `napcat-mcp-server/config.yml`；HTTP 占位服务和 MCP 命令入口都复用同一份配置文件。

## 5. 边界约束

- NapCat 反向 WS 只连接 `hub-service`。
- `napcat-mcp-server` 不实现消息收发，不做会话编排。
- QQ 查询接口的错误语义由 hub-service 转换为 HTTP 状态码，MCP 工具只负责把结果或错误返回给 agent-service。
