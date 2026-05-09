# DevSecOps AI Platform

## Table of Contents

1. [Overview](#overview)
2. [Project Presentation](#project-presentation)
   - [Project Context](#project-context)
   - [Problem Statement](#problem-statement)
   - [Project Objectives](#project-objectives)
   - [Analysis of Existing Approaches](#analysis-of-existing-approaches)
   - [Critical Evaluation of Existing Systems](#critical-evaluation-of-existing-systems)
   - [Proposed Solution](#proposed-solution)
3. [Needs Analysis](#needs-analysis)
   - [System Actors](#system-actors)
   - [Functional Requirements](#functional-requirements)
   - [Non-Functional Requirements](#non-functional-requirements)
4. [Architecture](#architecture)
   - [Global Architecture](#global-architecture)
   - [Agents Description](#agents-description)
5. [Workflow State Machine](#workflow-state-machine)
6. [API Endpoints](#api-endpoints)
7. [Configuration](#configuration)
8. [Installation & Local Setup](#installation--local-setup)
9. [Database Schema](#database-schema)
10. [Notes](#notes)

---

## Overview

DevSecOps AI Platform is an intelligent orchestration system that leverages AI agents to automate DevSecOps analysis, planning, and infrastructure artifact generation. The platform integrates advanced NLP models with deterministic failure analysis to provide a comprehensive CI/CD infrastructure solution with built-in error correction and human oversight.

**Key Features:**
- Automated repository analysis using LangGraph agents
- AI-driven DevSecOps planning
- Infrastructure artifact generation (Docker, Terraform, Kubernetes, CI/CD)
- Real-time build monitoring with WebSocket streaming
- Intelligent failure analysis and auto-correction
- Multi-step workflow validation and human review gates

---

## Project Presentation

### Project Context

The rapid adoption of containerization and cloud-native technologies has created significant challenges for development teams. Organizations struggle with:

- **Complexity**: Managing Docker builds, Kubernetes deployments, and infrastructure-as-code in a cohesive manner
- **Security**: Ensuring compliance with DevSecOps principles across the software supply chain
- **Automation**: Reducing manual configuration and error-prone infrastructure setup
- **Maintenance**: Keeping infrastructure definitions synchronized with application requirements

Traditional approaches rely on manual configuration, version control-based reviews, and ad-hoc infrastructure management. This process is time-consuming, error-prone, and difficult to scale across teams.

### Problem Statement

Development and DevOps teams face the following challenges:

1. **Infrastructure as Code Learning Curve**: Teams must master multiple DSLs (Dockerfile, Terraform, Kubernetes YAML, CI/CD configurations) simultaneously
2. **Consistency Violations**: Manual infrastructure generation leads to inconsistent configurations across environments
3. **Security Gaps**: Ad-hoc configurations often miss security best practices (image scanning, RBAC, network policies)
4. **Failure Recovery**: Build failures require manual diagnosis and intervention, increasing time-to-resolution
5. **Multi-Stage Approval**: Human review of generated infrastructure is necessary but lacks structured validation gates

### Project Objectives

The DevSecOps AI Platform aims to:

1. **Automate Infrastructure Generation**: Analyze repository structure and generate DevSecOps-compliant infrastructure automatically
2. **Intelligent Error Detection & Correction**: Implement deterministic and LLM-enhanced failure classification with actionable fix suggestions
3. **Structured Approval Workflows**: Provide multi-step review gates with role-based permissions
4. **Real-time Monitoring & Feedback**: Stream live build logs and execution state to users
5. **Extensible Agent Framework**: Enable future integration of Terraform, Kubernetes, and CI/CD-specific agents
6. **Cost Awareness**: Integrate cost estimation into infrastructure planning

### Analysis of Existing Approaches

**Manual Configuration**
- Teams manually write Dockerfile, Terraform, and CI/CD files
- Prone to errors and inconsistencies
- Requires deep domain expertise
- Non-scalable for large organizations

**Template-Based Generators**
- Use generic templates for common patterns
- Limited customization and context awareness
- Cannot adapt to unique repository requirements
- Do not address failure correction

**Single-Purpose Tools**
- Tools like Docker, Terraform, and GitHub Actions operate independently
- No unified orchestration or cross-tool consistency
- Failures in one tool lack context from others
- No integrated error correction or remediation

**Generic LLM Code Assistants**
- Claude, ChatGPT can generate code but lack domain specialization
- No built-in understanding of DevSecOps best practices
- Cannot run background analysis or maintain workflow state
- Not integrated with actual build infrastructure

### Critical Evaluation of Existing Systems

| Aspect | Manual | Templates | Single-Purpose | Generic LLM | **Our Platform** |
|--------|--------|-----------|-----------------|-------------|-----------------|
| Context Awareness | ❌ | ⚠️ | ❌ | ⚠️ | ✅ |
| Error Correction | ❌ | ❌ | ❌ | ⚠️ | ✅ |
| Workflow Orchestration | ❌ | ❌ | ❌ | ❌ | ✅ |
| Real-time Monitoring | ❌ | ❌ | ⚠️ | ❌ | ✅ |
| Security-First Design | ❌ | ⚠️ | ⚠️ | ⚠️ | ✅ |
| Scalability | ❌ | ⚠️ | ⚠️ | ✅ | ✅ |
| Cost Analysis | ❌ | ❌ | ❌ | ❌ | ✅ |

### Proposed Solution

The DevSecOps AI Platform proposes a **multi-agent orchestration system** with integrated failure correction:

1. **CodebaseAnalysisAgent**: Scans repositories to extract context (dependencies, structure, frameworks)
2. **PlannerAgent**: Generates DevSecOps plans based on codebase analysis
3. **InfrastructureAgent**: Generates Docker, Terraform, and Kubernetes artifacts
4. **DockerCorrectorAgent**: Analyzes build failures and suggests fixes
5. **ExecutionAgent**: Runs builds, monitors logs, and coordinates workflow state

**Key Innovations:**
- **Deterministic Failure Classification**: Rule-based + optional LLM enrichment for fast, reliable error diagnosis
- **Human-in-the-Loop Approval**: Multi-step workflow with review gates at critical junctures
- **Real-time WebSocket Streaming**: Live build logs and execution state updates
- **Cost-Aware Planning**: Infrastructure recommendations prioritize cost-efficiency
- **Extensible Agent Framework**: Ready for TerraformCorrectorAgent, KubernetesCorrectorAgent, CICDCorrectorAgent

---

## Needs Analysis

### System Actors

| Actor | Role | Interactions |
|-------|------|--------------|
| **Developer** | Submits repositories and approves plans | Uploads repo URL, reviews generated artifacts, approves infrastructure |
| **DevOps Engineer** | Reviews and refines generated infrastructure | Modifies artifacts, handles complex configurations, triggers retries |
| **Security Engineer** | Validates compliance and security posture | Reviews corrector suggestions, approves high-severity fixes |
| **CI/CD Pipeline** | Executes builds and infrastructure deployments | Runs Dockerfile builds, applies Terraform, deploys to Kubernetes |
| **LLM Service** | Provides enriched analysis and code generation | Claude API for planning, analysis, and LLM-enhanced correction |

### Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR1 | Accept GitHub repository URLs and clone repositories | High |
| FR2 | Analyze repository structure, dependencies, and frameworks | High |
| FR3 | Generate DevSecOps-compliant infrastructure artifacts | High |
| FR4 | Display generated artifacts for user review and approval | High |
| FR5 | Generate only approved artifacts | High |
| FR6 | Store task metadata, logs, plans, and results in database | High |
| FR7 | Stream live build logs to frontend via WebSocket | High |
| FR8 | Detect build failures and classify error types | High |
| FR9 | Suggest actionable fixes for common failure patterns | High |
| FR10 | Allow users to manually retry failed builds | High |
| FR11 | Estimate infrastructure costs for generated artifacts | Medium |
| FR12 | Support multiple LLM providers (Groq, GitHub Models, Claude) | Medium |
| FR13 | Support future agent extensions (Terraform, K8s, CI/CD correctors) | Low |

### Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NFR1 | API response time < 500ms for non-build operations | High |
| NFR2 | Support concurrent task execution | High |
| NFR3 | Persist all state to PostgreSQL database | High |
| NFR4 | Deploy via Docker Compose for local development | High |
| NFR5 | Provide comprehensive error handling and logging | High |
| NFR6 | Support authentication and authorization | Medium |
| NFR7 | Auto-scale infrastructure for production deployments | Low |
| NFR8 | Achieve 99.9% uptime for core services | Low |

---

## Architecture

### Global Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Frontend Layer                                 │
├────────────────────────────────────────────────────────────────────────┤
│  React Web UI (Next.js)                                                 │
│  ├─ Workflow Page: 8-step multi-step process                          │
│  ├─ Build Logs: Live WebSocket streaming                              │
│  ├─ Plan Review: Approve/reject infrastructure artifacts              │
│  └─ Corrector UI: Review & approve suggested fixes                    │
└────────────┬───────────────────────────────────────────────────────────┘
             │ REST API / WebSocket
             ▼
┌────────────────────────────────────────────────────────────────────────┐
│                          Backend Layer (FastAPI)                        │
├────────────────────────────────────────────────────────────────────────┤
│  API Routes                                                             │
│  ├─ POST /api/tasks/create                    (start workflow)        │
│  ├─ GET /api/execution/{task_id}              (fetch status)          │
│  ├─ POST /api/execution/docker/build/{id}    (start build)           │
│  ├─ WS /ws/execution/{task_id}                (live logs)             │
│  ├─ GET /api/corrector/{task_id}              (fetch analysis)        │
│  └─ POST /api/corrector/reanalyze/{task_id}  (re-analyze)            │
└────────────┬───────────────────────────────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────────────────────┐
│                      Orchestration Layer (LangGraph)                    │
├────────────────────────────────────────────────────────────────────────┤
│  Agent Graph                                                            │
│  ├─ OrchestratorAgent     (drives workflow)                           │
│  ├─ CodebaseAnalysisAgent (scans repo)                                │
│  ├─ PlannerAgent          (creates plan)                              │
│  ├─ InfrastructureAgent   (generates artifacts)                       │
│  ├─ ExecutionAgent        (runs builds)                               │
│  └─ CorrectionLayer                                                    │
│      ├─ log_sanitizer.py       (clean noise)                          │
│      ├─ error_extractor.py     (regex extraction)                     │
│      ├─ failure_classifier.py  (rule-based classification)            │
│      ├─ docker_corrector.py    (LLM-enhanced analysis)                │
│      └─ corrector_api.py       (exposure layer)                       │
└────────────┬───────────────────────────────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────────────────────┐
│                    Execution & Storage Layer                            │
├────────────────────────────────────────────────────────────────────────┤
│  ├─ Docker Build Engine   (build containerized apps)                  │
│  ├─ PostgreSQL Database   (persist task, execution, corrector state)  │
│  ├─ File Storage          (Dockerfiles, Terraform, manifests)         │
│  └─ LLM Providers         (Claude, Groq, GitHub Models)               │
└────────────────────────────────────────────────────────────────────────┘
```

### Agents Description

#### 1. OrchestratorAgent

**Responsibility**: Drives the entire workflow, coordinating between other agents.

**Inputs**:
- User prompt (repository URL, infrastructure requirements)
- Task metadata (task_id, user_id, timestamps)

**Outputs**:
- Workflow state (planning → approval → generation → execution)
- Coordinates calls to downstream agents
- Updates execution status in real-time

**Flow**:
```
user_input → analysis → planning → approval → generation → execution → completion
```

---

#### 2. CodebaseAnalysisAgent

**Responsibility**: Clones, scans, and parses GitHub repositories to extract context.

**Inputs**:
- GitHub repository URL
- GitHub token (optional, for private repos)
- Repository branch/tag

**Outputs**:
```json
{
  "repository_url": "https://github.com/user/repo",
  "primary_language": "python",
  "frameworks": ["FastAPI", "SQLAlchemy"],
  "dependencies": {
    "python": ["fastapi", "sqlalchemy", "pydantic"],
    "node": ["react", "typescript"]
  },
  "dockerfile_exists": true,
  "readme_summary": "...",
  "security_concerns": [
    "No input validation in API",
    "Hardcoded secrets in .env.example"
  ],
  "file_structure": {...}
}
```

**Flow**:
1. Clone repository from GitHub
2. Detect primary language and frameworks
3. Parse dependency files (requirements.txt, package.json, go.mod, etc.)
4. Scan for security concerns (secrets, vulnerabilities)
5. Generate repository context summary

---

#### 3. PlannerAgent

**Responsibility**: Creates a comprehensive DevSecOps execution plan based on codebase analysis.

**Inputs**:
- Repository context (from CodebaseAnalysisAgent)
- User requirements
- Security policies

**Outputs**:
```json
{
  "plan_id": "plan-uuid",
  "infrastructure_components": [
    {
      "type": "dockerfile",
      "name": "app",
      "security_score": 0.85,
      "features": ["multi-stage build", "non-root user", "vulnerability scanning"]
    },
    {
      "type": "terraform",
      "name": "aws-infrastructure",
      "estimated_cost": "$150/month"
    },
    {
      "type": "kubernetes",
      "name": "k8s-deployment"
    }
  ],
  "estimated_cost": "$150/month",
  "compliance_notes": ["OWASP Top 10 covered", "No hardcoded secrets"]
}
```

**Flow**:
1. Analyze repository context
2. Recommend infrastructure components
3. Estimate costs
4. Identify security improvements
5. Return plan for user approval

---

#### 4. InfrastructureAgent

**Responsibility**: Generates Dockerfile, Terraform, Kubernetes, and CI/CD artifacts.

**Inputs**:
- Repository context
- Approved plan
- Infrastructure specifications

**Outputs**:
```
Dockerfile
├── Multi-stage build
├── Security hardening (non-root user, minimal base image)
└── Health checks & entrypoints

Terraform
├── AWS/GCP/Azure resource definitions
├── Security group configurations
└── Cost-optimized defaults

Kubernetes
├── Deployment manifests
├── Service definitions
├── Network policies
└── RBAC configurations

CI/CD (GitHub Actions, GitLab CI)
├── Build pipeline
├── Test execution
├── Security scanning
└── Deployment stages
```

**Flow**:
1. Generate Dockerfile with best practices
2. Create Terraform modules for infrastructure
3. Build Kubernetes manifests
4. Generate CI/CD pipeline configurations
5. Return all artifacts for storage

---

#### 5. ExecutionAgent

**Responsibility**: Executes Docker builds, monitors logs, and manages workflow state.

**Inputs**:
- Dockerfile
- Docker build context
- Task metadata

**Outputs**:
```json
{
  "task_id": "task-uuid",
  "status": "docker_build_success | corrector_analysis_running | human_review_required | execution_failed",
  "build_log": "...",
  "exit_code": 0,
  "duration_ms": 45000,
  "corrector_analysis": {
    "status": "analyzed",
    "error_type": "permission_failure",
    "root_cause": "...",
    "retry_recommended": false,
    "fixes": [...]
  }
}
```

**Flow**:
1. Execute Docker build
2. Stream logs via WebSocket
3. On failure: trigger DockerCorrectorAgent
4. Wait for human review or auto-retry
5. Update execution state

---

#### 6. DockerCorrectorAgent

**Responsibility**: Analyzes build failures, classifies errors, and suggests fixes.

**Inputs**:
- Build logs (stdout/stderr)
- Exit code
- Dockerfile

**Processing Pipeline**:

```
Build Logs
    ▼
[log_sanitizer.py] → Remove ANSI, Docker noise
    ▼
[error_extractor.py] → Extract exit_code, failed_step, stack_trace
    ▼
[failure_classifier.py] → Rule-based classification (10 types)
    ▼
[docker_corrector.py] → Optional LLM enrichment
    ▼
CorrectorResult
```

**Output**:
```json
{
  "status": "analyzed",
  "error_type": "permission_failure",
  "confidence": 0.93,
  "root_cause": "The build process was denied access to /app/entrypoint.sh during Dockerfile step `RUN chmod +x entrypoint.sh`.",
  "failed_step": "RUN chmod +x entrypoint.sh",
  "error_excerpt": "Step 4/7 : RUN chmod +x /app/entrypoint.sh\nchmod: changing permissions of '/app/entrypoint.sh': Permission denied",
  "retry_recommended": false,
  "fixes": [
    {
      "title": "Add chmod to make scripts executable",
      "explanation": "Script entrypoint.sh needs execute permissions before ENTRYPOINT command.",
      "patch": "RUN chmod +x /app/entrypoint.sh",
      "severity": "high",
      "applies_to": "Dockerfile"
    }
  ],
  "llm_enriched": true
}
```

**Failure Classification (10 Types)**:

| Failure Type | Confidence | Detection Rule | Example |
|--------------|-----------|-----------------|---------|
| **base_image_failure** | 0.95 | base_image_pull_or_manifest_error | FROM python:99.0 (invalid version) |
| **build_context_failure** | 0.93 | dockerfile_copy_add_context_missing | COPY missing_file.txt . |
| **permission_failure** | 0.93 | permission_denied_or_eacces | chmod: Permission denied |
| **syntax_error** | 0.92 | syntax_or_parse_error | Invalid Dockerfile syntax |
| **environment_variable_failure** | 0.91 | env_var_missing_or_undefined | $UNDEFINED_VAR not set |
| **network_failure** | 0.90 | network_or_dns_or_ssl_error | Connection refused, DNS lookup failed |
| **package_manager_failure** | 0.89 | package_manager_resolve_or_install_error | apt-get: package not found |
| **missing_file** | 0.88 | file_not_found_enoent | no such file or directory |
| **dependency_failure** | 0.85 | import_or_module_or_linker_error | ImportError: No module named 'X' |
| **unknown_failure** | 0.30 | no_rule_matched | Unclassified error |

**Flow**:
1. Sanitize logs (remove ANSI codes, Docker build progress noise)
2. Extract error information (exit code, failed step, stack trace)
3. Classify error using priority-ordered rule chain
4. Optionally enrich with LLM analysis
5. Generate fix suggestions with code patches
6. Return analysis for human review or auto-retry

---

## Workflow State Machine

```
WORKFLOW START
    ▼
[USER SUBMITS REPO] → codebase_analysis_running
    ▼
[ANALYSIS COMPLETE] → planning
    ▼
[PLAN GENERATED] → approval_pending
    ▼
[USER APPROVES] → generating_artifacts
    ▼
[ARTIFACTS GENERATED] → ready_to_execute
    ▼
[START BUILD] → docker_build_running
    ▼
    ├─ exit_code == 0 ──────────────────► docker_build_success
    │                                     (WORKFLOW COMPLETE)
    │
    └─ exit_code != 0 ──────────────────► corrector_analysis_running (async)
                                          ▼
                                    [ANALYSIS COMPLETE]
                                          ▼
                                    retry_count < max_retries (3)
                                          │
                                          ├─ YES ─► human_review_required
                                          │         (AWAITING USER DECISION)
                                          │         ├─ [RETRY] ──► docker_build_running (loop)
                                          │         └─ [CANCEL] ─► execution_failed
                                          │
                                          └─ NO ───► execution_failed
                                                     (MAX RETRIES EXCEEDED)
```

**State Descriptions**:

| State | Description | User Action |
|-------|-------------|------------|
| codebase_analysis_running | Repository being analyzed | Wait |
| planning | DevSecOps plan being generated | Wait |
| approval_pending | Plan ready for review | Review & approve/reject |
| generating_artifacts | Infrastructure artifacts being generated | Wait |
| ready_to_execute | Artifacts ready, awaiting build start | Click "Start Build" |
| docker_build_running | Docker build in progress | Monitor logs |
| docker_build_success | Build completed successfully | View results |
| corrector_analysis_running | Build failed, analyzing failure | Wait |
| human_review_required | Analysis complete, awaiting manual decision | Review fixes & retry/cancel |
| execution_failed | Max retries exceeded or user cancelled | View error details |

---

## API Endpoints

### Task Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/tasks/create` | Create new workflow task |
| GET | `/api/tasks/` | List all tasks |
| GET | `/api/tasks/{task_id}` | Get task details |
| POST | `/api/tasks/plan-preview` | Preview plan without execution |

### Execution Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/execution/{task_id}` | Fetch execution state |
| POST | `/api/execution/docker/build/{task_id}` | Start Docker build |
| WS | `/ws/execution/{task_id}` | WebSocket for live build logs |

### Corrector / Failure Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/corrector/{task_id}` | Fetch corrector analysis |
| POST | `/api/corrector/reanalyze/{task_id}` | Re-analyze build logs |

### Health & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health/` | Health check |
| GET | `/` | API info |

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/devsecops

# LLM Configuration
LLM_PROVIDER=groq|github_models|claude  # Default: groq
GROQ_API_KEY=xxx
GROQ_MODEL=llama-3.3-70b-versatile
GITHUB_MODELS_API_KEY=xxx
CLAUDE_API_KEY=xxx

# Docker Configuration
DOCKER_HOST=unix:///var/run/docker.sock
MAX_BUILD_RETRIES=3

# Corrector Configuration
CORRECTOR_ENABLED=true
CORRECTOR_LLM_ENRICHMENT=true

# Security
SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
GITHUB_TOKEN=xxx  # For private repo access
```

### Key Configuration Files

- `backend/app/core/settings.py` — Application settings and environment loading
- `backend/app/core/app_factory.py` — FastAPI app initialization
- `docker-compose.yml` — Local development environment

---

## Installation & Local Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- PostgreSQL 14+
- Node.js 18+ (for frontend)
- Git

### Backend Setup

```bash
# Clone repository
git clone https://github.com/your-org/devsecops-ai-platform.git
cd devsecops-ai-platform

# Create Python virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Initialize database
python backend/scripts/init_db.py

# Run development server
python backend/run_dev.py
```

**Backend will be available at**: `http://localhost:8000`

### Frontend Setup

```bash
# Navigate to frontend directory
cd frontend-React

# Install dependencies
npm install

# Configure API endpoint
echo "VITE_API_URL=http://localhost:8000" > .env

# Start development server
npm run dev
```

**Frontend will be available at**: `http://localhost:5173`

### Docker Compose (Full Stack)

```bash
# Build and start all services
docker compose -f infrastructure/docker-compose.yml up --build

# Services will be available at:
# - Backend: http://localhost:8000
# - Frontend: http://localhost:3000
# - PostgreSQL: localhost:5432
# - Redis (optional): localhost:6379
```

### Database Initialization

```bash
# Apply migrations
alembic upgrade head

# Seed test data (optional)
python backend/scripts/seed_data.py
```

---

## Database Schema

### Tasks Table

```sql
CREATE TABLE tasks (
  id UUID PRIMARY KEY,
  user_id UUID NOT NULL,
  repository_url VARCHAR(255) NOT NULL,
  status VARCHAR(50) NOT NULL,
  plan JSONB,
  artifacts JSONB,
  execution_logs JSONB,
  result JSONB,
  error_details JSONB,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### Execution Table

```sql
CREATE TABLE execution (
  id UUID PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id),
  status VARCHAR(50) NOT NULL,
  phase VARCHAR(50) NOT NULL,
  exit_code INTEGER,
  stdout TEXT,
  stderr TEXT,
  build_log TEXT,
  duration_ms INTEGER,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

### Corrector Analysis Table

```sql
CREATE TABLE corrector_analysis (
  id UUID PRIMARY KEY,
  task_id UUID NOT NULL REFERENCES tasks(id),
  status VARCHAR(50) NOT NULL,
  error_type VARCHAR(50),
  confidence FLOAT,
  root_cause TEXT,
  fixes JSONB,
  llm_enriched BOOLEAN DEFAULT false,
  retry_count INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  analyzed_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);
```

---

## Notes

- Repository analysis only accepts `github.com` URLs
- Private repositories require a GitHub token at request time
- Cloned repositories are stored temporarily under `workspace/repos`
- Build logs are streamed in real-time via WebSocket
- All task state is persisted to PostgreSQL
- Failed builds trigger automatic failure analysis via DockerCorrectorAgent
- Maximum 3 automatic retries per failed build (configurable via MAX_BUILD_RETRIES)
- LLM enrichment for failure analysis is optional and can be disabled via CORRECTOR_LLM_ENRICHMENT
- Future extensions: TerraformCorrectorAgent, KubernetesCorrectorAgent, CICDCorrectorAgent
