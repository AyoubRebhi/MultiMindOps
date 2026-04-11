---
id: dockerfile_streamlit_frontend
artifact_type: dockerfile
language: python
framework: streamlit
project_type: web_ui
runtime: pip
dependencies: []
tags: [streamlit, frontend, docker]
description: Streamlit container pattern for a web UI service.
---
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8501
CMD ["sh", "-c", "streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0"]
