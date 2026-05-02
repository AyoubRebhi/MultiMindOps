# DevSecOps AI Platform - Architecture Report V3

## 1. Overview

The DevSecOps AI Platform is an agent-driven backend that converts natural language prompts and GitHub repository context into deployable DevSecOps artifacts. It combines repository analysis, LLM-based planning, RAG-assisted artifact generation, and contract-aware validation to produce Docker, Terraform, Kubernetes, and CI/CD outputs.

### System Purpose
- **End-to-end infrastructure generation**: From prompt to artifact contract without manual IaC drafting
- **Domain-aware artifact production**: RAG-backed templates reduce hallucination and encode best practices
- **Security-first execution**: repository gates, environment sanitization, and validation pipelines
- **Cost visibility**: runtime cost estimation alongside artifact generation
- **Modular orchestration**: separate Docker, Terraform, Kubernetes, and CI/CD agents for clearer responsibilities

### Main Components
- **Backend**: FastAPI API server in `backend/app`, with SQLAlchemy and PostgreSQL persistence
- **Frontend**: React + TypeScript UI under `frontend-React`
- **Orchestrator**: `backend/app/agents/orchestrator_agent.py` using LangGraph state graph
- **Agents**: `CodebaseAnalysisAgent`, `PlannerAgent`, `InfrastructureAgent`, `TerraformAgent`, `KubernetesAgent`, `CICDAgent`, `CostEstimationAgent`, `MultiPlanAgent`
- **RAG**: Qdrant knowledge base plus optional Chroma fallback for template retrieval
- **Security**: repository security service, env sanitization, artifact quality validator

## 2. Core Agents/Modules

### OrchestratorAgent
**Location**: `backend/app/agents/orchestrator_agent.py`  
**Frameworks/Libraries**: LangGraph, Python dataclasses, logging  
**Role and Responsibilities**: Workflow coordinator that implements fine-grained nodes for repository analysis, planning, cost estimation, multi-plan selection, Docker generation, Terraform generation, Kubernetes generation, security placeholder injection, artifact validation, CI/CD evaluation, and finalization.  
**Inputs and Outputs**:
- **Input**: `prompt`, `repo_url`, `repository_visibility`, `github_token`, `uploaded_env_input`, `auto_mode`
- **Output**: A complete state object containing `status`, `logs`, `plan`, `infra`, `terraform_outputs`, `validation`, `cicd`, `result`
```json
{
  "status": "completed",
  "logs": [...],
  "plan": {...},
  "infra": {...},
  "terraform_outputs": {...},
  "validation": {...},
  "cicd": {...},
  "result": {...}
}
```
**Execution Modes/Pipelines**: Full run, plan preview, generation after preview, auto plan selection, paused human validation  
**LLM Usage**: None directly; it routes and aggregates other LLM-backed agents

### CodebaseAnalysisAgent
**Location**: `backend/app/agents/codebase_analysis_agent.py`  
**Frameworks/Libraries**: GitHubService, repository parsing services, security services, repository registry  
**Role and Responsibilities**: Analyze a GitHub repository, compute cache decisions with fingerprinting, run security gated scans, perform intelligent LLM-assisted prioritization of files, build application profile, and emit an RAG-ready agent context.  
**Inputs and Outputs**:
- **Input**: `repo_url`, `repository_visibility`, `github_token`, `uploaded_env`
- **Output**: Repository analysis payload with security result, project summary, file tree, important files, categorized files, chunks, agent context, and application profile
```json
{
  "agent": "CodebaseAnalysisAgent",
  "repo_summary": "Node.js Express service",
  "file_tree": [{"path": "package.json", "type": "file"}],
  "important_files": ["package.json", "src/index.js"],
  "agent_context": {"application_profile": {...}, "planner_context": {...}},
  "repository_analysis": {
    "cache_status": "new_analysis",
    "decision": {...},
    "identity": {...}
  }
}
```
**Execution Modes/Pipelines**: Repository analysis with cache reuse or recomputation, security block handling  
**LLM Usage**: Not directly in the main analysis path; used indirectly by `LLMPriorityEngine` in the intelligent analysis pipeline

### PlannerAgent
**Location**: `backend/app/agents/planner_agent.py`  
**Frameworks/Libraries**: BaseAgent, LLMService, pydantic  
**Role and Responsibilities**: Produce a single infrastructure-first plan and normalize required artifacts. It validates the plan schema, enforces mandatory Terraform/Docker/GitHub Actions artifacts, and appends an infrastructure blueprint.  
**Inputs and Outputs**:
- **Input**: `prompt`, `planner_context`
- **Output**: Execution plan with ordered steps, artifact list, complexity estimate, and reasoning summary
```json
{
  "agent": "PlannerAgent",
  "steps": ["Define infrastructure using Terraform...", "Create Dockerfile..."],
  "required_artifacts": ["terraform/main.tf", "Dockerfile", ".github/workflows/ci-cd.yml"],
  "estimated_complexity": "medium",
  "reasoning_summary": "Infrastructure-first plan based on application profile"
}
```
**Execution Modes/Pipelines**: Single-plan generation with memory caching
**LLM Usage**: Groq (via `LLMService`) for plan synthesis

### MultiPlanAgent
**Location**: `backend/app/agents/multi_plan_agent.py`  
**Frameworks/Libraries**: BaseAgent, LLMService  
**Role and Responsibilities**: Generate plan variants and select a recommended plan for human review. Used in the plan preview / multi-plan phase.  
**Inputs and Outputs**:
- **Input**: `prompt`, `plan`, `cost_estimation`, `application_profile`
- **Output**: List of plan variants, recommended selection, scoring information
```json
{
  "agent": "MultiPlanAgent",
  "plans": [
    {"plan_id": "plan_0", "plan_variant": "balanced", "score": 8.5},
    {"plan_id": "plan_1", "plan_variant": "cost_saving", "score": 7.2}
  ],
  "recommended_plan": "balanced"
}
```
**Execution Modes/Pipelines**: Human-in-the-loop selection or auto-mode
**LLM Usage**: Groq for plan variant differentiation

### InfrastructureAgent
**Location**: `backend/app/agents/infrastructure_agent.py`  
**Frameworks/Libraries**: EnhancedBaseAgent, LLMService, ValidationService, RAGPipelineService, TemplateRetrievalService  
**Role and Responsibilities**: Generate Docker-focused artifacts only: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, and `.env.example`, using a ReAct loop, semantic retrieval, and fallback artifact hints. It resolves approved artifact lists and selects the best generated or fallback artifact.  
**Inputs and Outputs**:
- **Input**: `prompt`, `plan`, `infrastructure_context`, `approved_artifacts`
- **Output**: Docker artifact package, `validation_summary`, `context_used`, `rag` metadata, and `react_iterations`
```json
{
  "agent": "InfrastructureAgent",
  "artifacts": {
    "dockerfile": "FROM node:18-alpine...",
    "dockerignore": "node_modules/\n...",
    "docker_compose": "version: '3.8'..."
  },
  "react_iterations": 2,
  "validation_summary": {"status": "valid", "issues": []},
  "rag": {"enabled": true, "fallback_used": false}
}
```
**Execution Modes/Pipelines**: ReAct loop with up to 3 attempts, Qdrant first then Chroma fallback
**LLM Usage**: Groq for artifact generation

### TerraformAgent
**Location**: `backend/app/agents/terraform_agent.py`  
**Frameworks/Libraries**: EnhancedBaseAgent, LLMService, RAGPipelineService  
**Role and Responsibilities**: Generate a split Terraform project for AWS, including provider, backend, VPC, compute, variables, and outputs. It enforces a strict contract and rejects DSL contamination such as Kubernetes YAML inside HCL.  
**Inputs and Outputs**:
- **Input**: `prompt`, `plan`, `infrastructure_context`, `approved_artifacts`
- **Output**: Terraform artifacts, `terraform_outputs` contract, architecture type, and `react_iterations`
```json
{
  "agent": "TerraformAgent",
  "artifacts": {
    "terraform_providers": "provider \"aws\" {...}",
    "terraform_vpc": "resource \"aws_vpc\" {...}",
    "terraform_outputs": "output \"cluster_endpoint\" {...}"
  },
  "terraform_outputs": {
    "cluster_endpoint": "${terraform_output:cluster_endpoint}",
    "ecr_repository_url": "${terraform_output:ecr_repository_url}"
  },
  "architecture_type": "eks",
  "react_iterations": 2
}
```
**Execution Modes/Pipelines**: ReAct loop with Terraform-specific validation
**LLM Usage**: Groq for HCL generation

### KubernetesAgent
**Location**: `backend/app/agents/kubernetes_agent.py`  
**Frameworks/Libraries**: EnhancedBaseAgent, LLMService, RAGPipelineService  
**Role and Responsibilities**: Generate Kubernetes manifests that consume Terraform outputs, ensuring the controller uses symbolic terraform output references rather than hardcoded AWS values.  
**Inputs and Outputs**:
- **Input**: `terraform_outputs`, `app_config`, `plan`
- **Output**: Kubernetes artifacts, `generated_artifacts`, and `react_iterations`
```json
{
  "agent": "KubernetesAgent",
  "artifacts": {
    "kubernetes_deployment": "apiVersion: apps/v1\nkind: Deployment\n...",
    "kubernetes_service": "apiVersion: v1\nkind: Service\n..."
  },
  "generated_artifacts": ["kubernetes/deployment.yaml", "kubernetes/service.yaml"],
  "react_iterations": 1
}
```
**Execution Modes/Pipelines**: ReAct loop with Kubernetes validation
**LLM Usage**: Groq for YAML generation

### CICDAgent
**Location**: `backend/app/agents/cicd_agent.py`  
**Frameworks/Libraries**: BaseAgent, CicdHandoffService, CicdWorkflowBuilderService, ArtifactContractService, CicdContractValidationService, RAGPipelineService  
**Role and Responsibilities**: Normalize artifact handoff contracts, detect runtime and CI/CD candidates, optionally enrich CI/CD context with semantic RAG, and generate CI/CD workflow artifacts. It returns a contract-safe CI/CD handoff payload rather than executing deployment.  
**Inputs and Outputs**:
- **Input**: `handoff_context`, `github_token`
- **Output**: CI/CD artifact package, validation status, artifact contract, readiness summary
```json
{
  "agent": "CICDAgent",
  "artifacts": {"github_actions_workflow": "name: CI/CD..."},
  "validation": {"status": "valid", "diagnostic": {...}},
  "artifact_contract": {...}
}
```
**Execution Modes/Pipelines**: CI/CD contract evaluation and artifact preparation
**LLM Usage**: None

### CostEstimationAgent
**Location**: `backend/app/agents/cost_estimation_agent.py`  
**Frameworks/Libraries**: BaseAgent  
**Role and Responsibilities**: Estimate expected monthly cost based on the generated plan and application profile.  
**Inputs and Outputs**:
- **Input**: `plan`, `application_profile`
- **Output**: Cost estimation with `monthly_cost` and profile label
```json
{
  "agent": "CostEstimationAgent",
  "monthly_cost": 189.50,
  "cost_profile": "balanced"
}
```
**Execution Modes/Pipelines**: Optional estimation step before plan selection
**LLM Usage**: None

## 3. Workflow Topology

```
User Request (API)
    │
    ▼
FastAPI Router (/tasks)
    │
    ▼
OrchestratorAgent Graph
    │
    ├─ initialize
    │
    ├─ analyze_repository (if repo_url)
    │
    ├─ planning_phase
    │
    ├─ cost_estimation
    │
    ├─ multi_plan_phase
    │
    ├─ plan_selection / human_validation
    │
    ├─ generation_phase (InfrastructureAgent)
    │
    ├─ terraform_phase (TerraformAgent)
    │
    ├─ kubernetes_phase (KubernetesAgent)
    │
    ├─ security_scan_phase (placeholder)
    │
    ├─ validation_phase
    │
    ├─ cicd
    │
    └─ finalize
```

## 4. Caching & Memory Strategy

### Repository Registry Caching
- **Purpose**: Avoid redundant GitHub repository analysis
- **Implementation**: PostgreSQL registry via `RepositoryRegistryService`
- **Key**: `normalized_url + branch + commit_sha + ANALYSIS_VERSION + env_fingerprint`
- **Invalidation**: Commit change, branch change, version bump, env fingerprint or file count change
- **Reuse**: Cached analysis is returned with `cache_status: "reused"`

### Agent Memory (Short-term)
- **Purpose**: Cache repeated LLM prompts/responses within each agent
- **Implementation**: In-process `AgentMemory` per agent
- **Threshold**: Only reuse cached entries when confidence ≥ 0.7
- **Decay**: 15% confidence drop per failed ReAct iteration
- **Scope**: Session-scoped, not persisted across process restarts

### RAG Knowledge Base
- **Purpose**: Provide domain-specific templates and guidance for artifact generation
- **Implementation**: Qdrant vector DB; Chroma fallback for template retrieval
- **Content**: DevSecOps corpus covering Terraform, Kubernetes, Docker, CI/CD, security, cloud patterns
- **Retrieval**: `RAGPipelineService` retrieves semantics and builds prompt context
- **Ingestion**: `rag/scripts/ingest_qdrant.py`, `rag/scripts/ingest_templates.py`

## 5. Validation & Security

### Security Gates
- **Repository Security**: `RepositorySecurityService` can block high-risk repos before generation
- **Environment Sanitization**: `.env` detection and sanitization via `EnvSanitizerService`
- **Security Score Transformer**: Normalizes repository and env runtime security into a summary
- **Artifact Validation**: `ValidationService` verifies generated artifacts by rules

### Artifact Validation
- **Docker**: Ensures Dockerfile and compose artifacts exist and meet policy checks
- **Kubernetes**: Ensures deployment/service YAML and terraform output references are present; rejects hardcoded ECR URLs
- **Terraform**: Ensures required outputs and file sections exist; rejects YAML contamination in HCL
- **GitHub Actions**: CI/CD status normalization and contract validation via `CicdContractValidationService`

### Routing Logic
- **Conditional execution**: Skips terraform/kubernetes phases if not requested in plan
- **Security blocking**: Halts workflow early when repository gate returns `blocked`
- **Validation gating**: Workflow can conclude with `partial_success` or `invalid` based on validation
- **Human approval**: Supports `auto_mode`, explicit plan approval, rejection, and replan requests

## 6. CI/CD Integration

### Workflow Generation
- **Templates**: CI/CD workflow artifacts are prepared by `CicdWorkflowBuilderService`
- **Integration**: `CICDAgent` receives a normalized handoff contract and runtime detection result
- **Artifacts**: Outputs include GitHub Actions workflows and CI/CD artifact statuses

### Template Usage
- **Retrieval**: RAG-based CI/CD context is optionally retrieved for `doc_type='cicd'`
- **Fallback**: Defaults apply when semantic context is unavailable
- **Validation**: Output is normalized and validated against the artifact contract before final handoff

### Fallback Strategies
- **ReAct Loop**: Infrastructure, Terraform, and Kubernetes agents retry on quality issues
- **Template Fallback**: InfrastructureAgent falls back to local artifact hints when RAG is unavailable
- **Partial Delivery**: The orchestrator still finalizes with partial success if not all artifacts are generated

## 7. Global Data Flow

```
User Input (Web UI)
    │
    ▼
React Frontend
    │
    ▼
FastAPI Backend (/tasks endpoint)
    │
    ▼
OrchestratorAgent.run()
    │
    ├─ setup state and logs
    │
    ├─ CodebaseAnalysisAgent analyzes repo and builds planner/RAG context
    │
    ├─ PlannerAgent produces an infrastructure-first plan
    │
    ├─ CostEstimationAgent estimates monthly cost
    │
    ├─ MultiPlanAgent optionally creates plan variants
    │
    ├─ (optional) Human approves selected plan
    │
    ├─ InfrastructureAgent generates Docker artifacts with RAG and fallback hints
    │
    ├─ TerraformAgent generates AWS Terraform project and outputs contract
    │
    ├─ KubernetesAgent generates manifests referencing terraform_outputs
n    │
    ├─ Security scan placeholder is injected for future pipeline integration
    │
    ├─ ArtifactQualityValidator evaluates generated artifacts
    │
    ├─ CICDAgent prepares CI/CD workflow handoff and validation
    │
    └─ Final response is returned with status, artifact contract, and logs
```

## 8. Key Decisions & Optimizations

### Agent specialization
- **Decision**: Move Docker, Terraform, and Kubernetes generation into separate agents
- **Rationale**: Avoid DSL contamination and keep each artifact domain-specific
- **Impact**: More precise validation and lower cross-artifact drift

### LangGraph orchestration
- **Decision**: Use a state graph for workflow routing
- **Rationale**: Supports conditional phases, pausing, and graceful termination
- **Impact**: Clear execution trace and flexible plan workflows

### ReAct loop where it matters
- **Decision**: Apply iterative refinement to content-heavy agents (`InfrastructureAgent`, `TerraformAgent`, `KubernetesAgent`)
- **Rationale**: Complex artifact generation benefits from error detection and retry
- **Impact**: Higher quality outputs and built-in fallback handling

### RAG-first retrieval with fallback
- **Decision**: Query Qdrant first, with Chroma fallback for template retrieval
- **Rationale**: Maintain semantic guidance while recovering from unavailable vector stores
- **Impact**: Robust template guidance across artifact domains

### Contract-driven handoff
- **Decision**: Use structured contracts (`terraform_outputs`, artifact groups/statuses) between agents
- **Rationale**: Avoid hardcoded values and enforce integration points
- **Impact**: Kubernetes manifests and CI/CD workflows can safely consume upstream outputs

### Human-in-the-loop plan review
- **Decision**: Pause for plan selection and approval via `plan_preview`
- **Rationale**: Complex infrastructure plans may need explicit user confirmation
- **Impact**: Better alignment with user intent and safer artifact generation

## 9. Comparative Summary Table

| Component | Framework | LLM Usage | Iterations | Caching | Validation | Security |
|-----------|-----------|-----------|------------|---------|------------|----------|
| **OrchestratorAgent** | LangGraph | None | N/A | State persistence | Workflow routing | Repository gating |
| **CodebaseAnalysisAgent** | Custom repo analysis | Indirect via LLMPriorityEngine | N/A | Registry cache | File parsing | Security gate |
| **PlannerAgent** | BaseAgent | Groq | Single | Memory cache | Plan schema | None |
| **MultiPlanAgent** | BaseAgent | Groq | Single | None | Plan comparison | None |
| **InfrastructureAgent** | EnhancedBaseAgent | Groq | ReAct up to 3 | Memory cache | Docker artifact validation | None |
| **TerraformAgent** | EnhancedBaseAgent | Groq | ReAct up to 3 | Memory cache | HCL contract & contamination checks | None |
| **KubernetesAgent** | EnhancedBaseAgent | Groq | ReAct up to 2 | Memory cache | Kubernetes YAML validation | None |
| **CICDAgent** | BaseAgent | None | N/A | None | CI/CD contract validation | Workflow security |
| **CostEstimationAgent** | BaseAgent | None | N/A | None | Cost calculation | None |

---

*Report generated on May 2, 2026 - DevSecOps AI Platform Architecture Analysis*</content>
<parameter name="filePath">c:\Users\ayoub\OneDrive\Bureau\Stage pfe Esprit\code\devsecops-ai-platform\documentations\architecture_report_V3.md