FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY skill-service /app/skill-service
COPY skills /app/skills
RUN uv pip install --system /app/skill-service
CMD ["skill-service"]
