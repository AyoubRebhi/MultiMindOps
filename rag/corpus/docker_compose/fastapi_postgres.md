---
id: compose_fastapi_postgres
artifact_type: docker_compose
language: python
framework: fastapi
project_type: api_backend
runtime: docker_compose
dependencies: [postgres]
tags: [fastapi, postgres, compose]
description: Docker Compose pattern for FastAPI with PostgreSQL.
---
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: ${DATABASE_URL}
    depends_on:
      - db

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    ports:
      - "5432:5432"
