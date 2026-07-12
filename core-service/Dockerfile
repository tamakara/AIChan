FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_SYSTEM_PYTHON=1

RUN pip install --no-cache-dir uv==0.7.2

WORKDIR /app
COPY core-service/pyproject.toml ./
COPY core-service/src ./src
COPY core-service/config.yml ./core-service/config.yml
COPY core-service/prompts ./core-service/prompts
COPY skills ./skills
RUN uv pip install --system .

EXPOSE 8020
CMD ["core-service"]
