FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY gateway/channels/cli/requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

COPY gateway/channels/cli/cli_gateway.py /app/cli_gateway.py

EXPOSE 8765

CMD ["python", "cli_gateway.py"]
