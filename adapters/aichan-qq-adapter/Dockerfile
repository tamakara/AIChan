FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY . /app
RUN uv pip install --system /app
CMD ["aichan-qq-adapter"]
