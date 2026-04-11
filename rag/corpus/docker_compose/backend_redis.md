---
id: compose_backend_redis
artifact_type: docker_compose
language: python
framework: generic
project_type: backend_service
runtime: docker_compose
dependencies: [redis]
tags: [backend, redis, compose]
description: Compose pattern for a backend service with Redis.
---
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      REDIS_URL: ${REDIS_URL}
    depends_on:
      - redis

  redis:
    image: redis:7
    ports:
      - "6379:6379"
