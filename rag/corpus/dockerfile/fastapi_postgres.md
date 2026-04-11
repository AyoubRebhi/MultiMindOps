---
id: dockerfile_fastapi_postgres
artifact_type: dockerfile
language: python
framework: fastapi
project_type: api_backend
runtime: pip
dependencies: [postgres]
tags: [uvicorn, postgres, api, docker]
description: FastAPI Dockerfile pattern aligned with a PostgreSQL-backed service.
---
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
