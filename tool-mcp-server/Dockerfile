FROM python:3.12-slim

LABEL io.docker.server.metadata='{"name":"tool-mcp-server","description":"Expose AICHAN QQ, file, image understanding, and video understanding tools as MCP tools.","command":["tool-mcp-mcp"]}'

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1
ENV UV_HTTP_TIMEOUT=180
ENV UV_HTTP_RETRIES=8
ENV PIP_DEFAULT_TIMEOUT=180

RUN pip install --no-cache-dir --retries 8 --timeout 180 uv==0.7.2

WORKDIR /app

COPY pyproject.toml ./
COPY config.yml ./tool-mcp-server/config.yml
COPY src ./src

RUN /bin/sh -c 'for i in 1 2 3; do uv pip install --system . && exit 0; echo "uv pip install failed, retry ${i}/3"; sleep 5; done; exit 1'

EXPOSE 8030

CMD ["tool-mcp-mcp"]
