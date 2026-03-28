FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY aichan/ /app/

RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "main.py"]
