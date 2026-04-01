---
id: dockerfile_fastapi_uvicorn
artifact_type: dockerfile
language: python
framework: fastapi
project_type: api_backend
runtime: pip
dependencies: []
tags: [uvicorn, api, docker]
description: Minimal Dockerfile for a FastAPI backend started with uvicorn.
---
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"]
