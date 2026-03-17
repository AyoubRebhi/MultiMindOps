# 🚀 DevSecOps AI Platform

## 📌 Overview

DevSecOps AI Platform is an intelligent platform designed to automate and orchestrate DevSecOps workflows using AI-powered agents.

The system leverages a **multi-agent architecture** to analyze user requests, generate execution plans, and simulate DevOps pipelines including CI/CD, containerization, security scanning, deployment, and monitoring.

---

## 🧠 Architecture

The platform follows a modular architecture:

```
devsecops-ai-platform/
│
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/          # API routes
│   │   ├── core/         # Configurations
│   │   ├── database/     # DB setup
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   └── main.py       # Entry point
│
├── agents/               # AI Agents system
│   ├── base_agent.py
│   ├── planner_agent.py
│   ├── orchestrator_agent.py
│
├── infrastructure/       # Docker configuration
│   └── docker-compose.yml
│
├── .env.example
├── requirements.txt
└── README.md
```

---

## ⚙️ Tech Stack

### Backend

* FastAPI
* SQLAlchemy
* PostgreSQL
* Pydantic

### DevOps

* Docker
* Docker Compose

### AI / Agents (Sprint 1)

* Rule-based Planner Agent
* Orchestrator Agent

---

## 🤖 Multi-Agent System

### 🔹 Planner Agent

Transforms user prompts into structured DevOps execution plans.

Example output:

* CI/CD pipeline generation
* Dockerfile creation
* Kubernetes manifests
* Security scanning steps
* Deployment and monitoring

---

### 🔹 Orchestrator Agent

Coordinates agents and manages execution flow:

* Receives user request
* Calls Planner Agent
* Returns structured result

---

## 🗄️ Database

PostgreSQL is used for persistent storage.

### Table: `tasks`

| Field         | Description                      |
| ------------- | -------------------------------- |
| id            | Unique task ID (UUID)            |
| prompt        | User request                     |
| status        | Task status                      |
| plan          | Generated execution plan (JSONB) |
| logs          | Execution logs (JSONB)           |
| result        | Final result (JSONB)             |
| error_message | Error details                    |
| created_at    | Timestamp                        |
| updated_at    | Timestamp                        |

---

## 🔌 API Endpoints

### Root

```
GET /
```

### Health Check

```
GET /health/
```

### Create Task

```
POST /tasks/
```

Request:

```json
{
  "prompt": "Deploy a FastAPI app with Docker and CI/CD"
}
```

---

### Get Task

```
GET /tasks/{task_id}
```

---

### List Tasks

```
GET /tasks/
```

---

## 🐳 Docker Usage

### Build & Run

```bash
docker compose -f infrastructure/docker-compose.yml up --build
```

---

### Services

* Backend → http://localhost:8000
* PostgreSQL → port 5432

---

## 🧪 Testing

### Swagger UI

```
http://localhost:8000/docs
```

---

### Example Request

```bash
curl -X POST http://127.0.0.1:8000/tasks/ \
-H "Content-Type: application/json" \
-d '{"prompt":"Deploy FastAPI with Docker and Kubernetes"}'
```

---

## 📊 Features (Sprint 1)

* FastAPI backend
* PostgreSQL integration
* Task management system
* Multi-agent orchestration
* Execution plan generation
* JSONB logging system
* Dockerized infrastructure

---

## 🚧 Future Improvements

* Integration with LLMs (OpenAI / LangChain)
* CI/CD pipeline generation
* Security agent (DevSecOps scanning)
* Kubernetes deployment automation
* Monitoring and alerting
* Frontend dashboard

---

## 👨‍💻 Author

Ayoub Rebhi
DevSecOps AI Platform — PFE Project

---
