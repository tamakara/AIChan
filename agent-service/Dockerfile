FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1

COPY --from=ghcr.io/astral-sh/uv:0.7.2 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN uv pip install --system .

EXPOSE 8000

CMD ["agent-service"]
