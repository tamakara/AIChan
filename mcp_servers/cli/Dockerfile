FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 使用 uv 管理依赖（workspace 模式）。
RUN pip install --no-cache-dir uv

# 构建上下文为 `mcp_servers/`，此处复制整个 workspace。
COPY . /app/

# 仅同步 cli-mcp-server 包所需依赖，避免安装无关成员。
RUN uv sync --frozen --no-dev --package cli-mcp-server

EXPOSE 9000

# 从 workspace 根目录启动 CLI 模块入口。
CMD ["uv", "run", "--package", "cli-mcp-server", "python", "-m", "cli.server"]
