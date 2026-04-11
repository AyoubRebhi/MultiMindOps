---
id: dockerfile_python_simple
artifact_type: dockerfile
language: python
framework: generic
project_type: backend_service
runtime: pip
dependencies: []
tags: [python, docker]
description: Simple Python backend Dockerfile when no specialized framework is detected.
---
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python main.py"]
