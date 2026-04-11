---
id: compose_fastapi_streamlit_postgres
artifact_type: docker_compose
language: python
framework: fastapi
project_type: multi_service_application
runtime: docker_compose
dependencies: [postgres]
tags: [fastapi, streamlit, postgres, compose]
description: Compose pattern for backend FastAPI, frontend Streamlit, and PostgreSQL.
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
      GROQ_API_KEY: ${GROQ_API_KEY}
    depends_on:
      - db

  frontend:
    build:
      context: .
      dockerfile: Dockerfile
    command: streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
    ports:
      - "8501:8501"
    depends_on:
      - backend

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
