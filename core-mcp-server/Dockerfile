FROM python:3.12-slim

LABEL io.docker.server.metadata='{"name":"core-mcp-server","description":"Expose AICHAN file, memory, image, and video tools.","command":["core-mcp-server"]}'

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv==0.7.2
WORKDIR /app
COPY pyproject.toml ./
COPY config.yml ./core-mcp-server/config.yml
COPY src ./src
RUN uv pip install --system .

EXPOSE 8030
CMD ["core-mcp-server", "--transport", "streamable-http"]
