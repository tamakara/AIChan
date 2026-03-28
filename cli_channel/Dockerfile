FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir "fastapi>=0.118.0" "uvicorn>=0.37.0" "pydantic>=2.0"

COPY cli_channel/cli_server.py /app/cli_server.py

EXPOSE 8765

CMD ["python", "cli_server.py"]
