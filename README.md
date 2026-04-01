# DevSecOps AI Platform

## Overview

DevSecOps AI Platform is a prototype that uses AI agents to analyze a repository,
prepare a DevSecOps plan, and generate infrastructure artifacts after user review.

The application currently includes:

- a FastAPI backend
- a Streamlit frontend
- a LangGraph-based orchestration layer
- PostgreSQL persistence for tasks, logs, plans, and results

## Architecture

```text
devsecops-ai-platform/
|-- backend/                 FastAPI application
|   |-- app/
|   |   |-- api/             API routes
|   |   |-- core/            settings and app factory
|   |   |-- database/        SQLAlchemy setup
|   |   |-- models/          database models
|   |   |-- schemas/         request and response schemas
|   |   |-- services/        business logic and integrations
|   |   `-- main.py          ASGI entry point
|-- frontend/                Streamlit user interface
|-- agents/                  planner, analysis, and infrastructure agents
|-- prompts/                 system prompts used by agents
|-- infrastructure/          Docker Compose setup
`-- workspace/               temporary cloned repositories
```

## Runtime flow

1. The user submits a prompt from the Streamlit frontend.
2. The backend optionally clones and scans a GitHub repository.
3. The orchestrator builds repository context and asks the planner for a plan.
4. The frontend shows the required artifacts for user approval.
5. The backend generates only the approved artifacts and stores the result.

## Main components

### Backend

- Entry point: `backend.app.main:app`
- App factory: `backend/app/core/app_factory.py`
- Task routes: `backend/app/api/routes/tasks.py`

### Agents

- `OrchestratorAgent`: drives the workflow
- `CodebaseAnalysisAgent`: clones, scans, and parses repositories
- `PlannerAgent`: creates the execution plan
- `InfrastructureAgent`: generates infrastructure artifacts

### Database

The project is configured for PostgreSQL.

The `tasks` table stores:

- task metadata
- execution status
- generated plan
- workflow logs
- final result
- error details

## API endpoints

- `GET /`
- `GET /health/`
- `POST /tasks/`
- `GET /tasks/`
- `GET /tasks/{task_id}`
- `POST /tasks/plan-preview`
- `POST /tasks/generate`

## Configuration

Environment variables are loaded from `.env`.

Important variables:

- `DATABASE_URL`
- `GROQ_API_KEY`
- `GROQ_MODEL`

Do not hardcode secrets in source files. Use local environment variables or `.env`.

## Local run

### Backend

```bash
python backend/run_dev.py
```

This dev launcher keeps auto-reload enabled but excludes volatile runtime folders such as `workspace/repos` and `rag/chroma`, which prevents repository cloning or Chroma indexing from restarting the API mid-request.

### Frontend

```bash
streamlit run frontend/app.py
```

### Docker

```bash
docker compose -f infrastructure/docker-compose.yml up --build
```

## Notes

- Repository analysis only accepts `github.com` URLs.
- Private repositories require a GitHub token at request time.
- Cloned repositories are stored temporarily under `workspace/repos`.
