# DevSecOps AI Platform - Architecture Complète

## Réponse Rapide: OUI, c'est un framework multi-agents

**Pas UN agent**, mais une **plateforme orchestrée** de 4+ agents spécialisés coordonnés par LangGraph.

---

## 1. Architecture Globale

```
┌────────────────────────────────────────────────────────────────┐
│                     FastAPI Application                        │
│  (main.py → create_app() → APIRouter(prefix=/tasks))           │
└────────────────┬───────────────────────────────────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │  POST /tasks/   │  ← User submits prompt + repo_url
        │ POST /task/:id  │
        │ GET /tasks      │
        │ POST /plan-preview
        └────────┬────────┘
                 │
         ┌───────▼──────────┐
         │ OrchestratorAgent│  ← LangGraph state machine
         │ (Multi-agent     │     (controls workflow)
         │  coordinator)    │
         └───────┬──────────┘
                 │
    ┌────────────┼────────────┬─────────────┬──────────────┐
    ▼            ▼            ▼             ▼              ▼
[Codebase]  [Planner]   [Infrastructure] [CICD]      [Database/
 Analysis    Agent      Agent            Agent        Registry]
  Agent                                               Services
```

---

## 2. Les 4 Agents Principaux

### A. **CodebaseAnalysisAgent** (ENTRY POINT)
```
INPUT:  repo_url, github_token, repository_visibility
OUTPUT: Code structure, security assessment, file tree, agent_context

WORKFLOW:
  ├─ 1. Build identity (repo fingerprint)
  ├─ 2. Check cache (registry lookup)
  ├─ 3. If changed or new:
  │   ├─ Clone repo from GitHub
  │   ├─ Run security gate (block if risky)
  │   ├─ Parse repository
  │   ├─ Detect & sanitize .env files
  │   ├─ Generate project summary
  │   ├─ Identify key entrypoints
  │   ├─ Chunk for RAG embeddings
  │   └─ Save to registry
  └─ 4. Return analysis_output
```

**Inheritance**: `BaseAgent` (abstract interface only)

---

### B. **PlannerAgent**
```
INPUT:  User prompt, repository analysis (optional)
OUTPUT: Ranked execution plan + artifact list

WORKFLOW:
  ├─ 1. Generate 3 plan variants (LLM call):
  │   ├─ "minimal"       (smallest scope)
  │   ├─ "standard"      (balanced)
  │   └─ "comprehensive" (full infracode)
  │
  ├─ 2. Score each variant on:
  │   ├─ Artifact coverage (does it cover all needed artifacts?)
  │   ├─ Step quality     (clear, numbered steps?)
  │   ├─ Reasoning depth  (specific enough?)
  │   └─ Complexity fit   (medium beats extreme)
  │
  ├─ 3. Select best-scoring plan
  │
  └─ 4. Return as PlannerResponseSchema (+ all 3 variants in memory)

SCHEMA:
{
  "agent": "PlannerAgent",
  "steps": ["Step 1: ...", "Step 2: ..."],
  "required_artifacts": ["Dockerfile", "docker-compose.yml", ...],
  "estimated_complexity": "medium",
  "reasoning_summary": "..."
}
```

**Inheritance**: `BaseAgent`
**LLM**: Groq (via LLMService)

---

### C. **InfrastructureAgent**
```
INPUT:  prompt, plan, infrastructure_context
OUTPUT: Generated Docker/K8s/Terraform/CI-CD artifacts

WORKFLOW (with ReAct loop):

Iteration 1:
  ├─ Map plan to infrastructure context
  ├─ Retrieve similar templates from RAG
  ├─ Call LLM with prompt + templates
  ├─ Parse response (extract Dockerfile, docker-compose, etc.)
  └─ Evaluate quality

  If quality issues:
    ├─ Collect issues
    ├─ Append refinement prompt
    └─ Retry (up to 3 times)

  If valid:
    ├─ Validate each artifact (Dockerfile syntax, etc.)
    ├─ Cache in memory
    └─ Return artifacts

OUTPUT:
{
  "agent": "InfrastructureAgent",
  "artifacts": {
    "dockerfile": {...},
    "docker-compose": {...},
    "kubernetes_manifest": {...},
    "terraform": {...},
    "github_actions_workflow": {...}
  },
  "react_iterations": 2,
  "validation_summary": {...}
}
```

**Inheritance**: `EnhancedBaseAgent` (gains ReAct loop + memory)
**Quality Gate**: `_evaluate_infra_quality()` (Dockerfile validation, etc.)

---

### D. **CICDAgent**
```
INPUT:  artifacts, plan, approval status
OUTPUT: CI/CD pipeline configuration + quality metrics

WORKFLOW:
  ├─ 1. Validate artifact contract
  ├─ 2. Map artifacts to CI/CD steps
  ├─ 3. Generate GitHub Actions workflows
  ├─ 4. Configure security scanners
  └─ 5. Return deployment plan

(Minimal example - extend as needed)
```

---

## 3. LangGraph Orchestrator - State Machine

```
START
  │
  ├─ Initialize state
  │  ├─ logs: []
  │  ├─ status: "initialized"
  │  └─ timestamps: {...}
  │
  ▼
┌─────────────────────────────────────┐
│ 1. CONDITIONAL: Has repo_url?       │
├─────────────────────────────────────┤
│  YES ─→ analyze_repository()        │
│  NO  ─→ skip to planner             │
└────────┬──────────────────┬─────────┘
         │                  │
         ▼                  │
    ┌──────────────┐        │
    │ CodebaseAnalysis
    │ Security gate?│        │
    │ ├─ BLOCKED   │        │
    │ │  ├→ status="blocked"
    │ │  └→ finalize()       │
    │ └─ OK (or skipped) ────┼──┐
    └──────────────┘        │  │
                            │  │
         ┌──────────────────┘  │
         │                     │
         ▼                     │
    ┌─────────────────────────┴──┐
    │ 2. planner_agent()          │
    │ ├─ Input: prompt + context  │
    │ ├─ Output: plan + artifacts │
    ├─────────────────────────────┤
    │ Empty plan?                 │
    │ ├─ YES → finalize()         │
    │ └─ NO  → infrastructure()   │
    └────┬────────────────────────┘
         │
         ▼
    ┌──────────────────────────────┐
    │ 3. infrastructure_agent()    │
    │ ReAct loop (up to 3 iters)  │
    │ Generate artifacts + validate
    ├──────────────────────────────┤
    │ Validation: INVALID?         │
    │ ├─ YES → finalize() [error]  │
    │ └─ NO → cicd()               │
    └────┬─────────────────────────┘
         │
         ▼
    ┌──────────────────────────────┐
    │ 4. cicd_agent()              │
    │ Generate CI/CD pipelines     │
    ├──────────────────────────────┤
    │ All processing done          │
    └────┬──────────────────────────┘
         │
         ▼
    ┌──────────────────────────────┐
    │ 5. finalize()                │
    │ ├─ Set status (completed/blocked/error)
    │ ├─ Compile result            │
    │ ├─ Append logs               │
    │ └─ Return state              │
    └────┬──────────────────────────┘
         │
         ▼
        END
```

---

## 4. Data Flow - Exemple Complet

```
User Request:
{
  "prompt": "Create a secure Node.js CI/CD pipeline",
  "repo_url": "https://github.com/user/node-app",
  "repository_visibility": "public",
  "github_token": null
}

      ↓

[1] CodebaseAnalysisAgent.run()
    ├─ Clone repo → /tmp/node-app
    ├─ Security scan → ✓ OK
    ├─ Parse files:
    │  ├─ file_tree: [{path: "package.json"}, {path: "src/index.js"}, ...]
    │  ├─ important_files: ["package.json", "Dockerfile (missing)"]
    │  ├─ key_entrypoints: ["src/index.js"]
    │  ├─ env_files: [] (none detected)
    │  └─ chunks: ["{Node.js, npm, package.json...", ...]
    │
    └─ Output:
        {
          "agent": "CodebaseAnalysisAgent",
          "repo_summary": "Production Node.js app...",
          "file_tree": [...],
          "important_files": [...],
          "agent_context": {
            ...RAG-ready context...
          },
          "repository_analysis": {
            "cache_status": "new_analysis",
            "record_id": "12345"
          }
        }

      ↓

[2] PlannerAgent.run()
    ├─ LLM call with:
    │  ├─ Original prompt
    │  ├─ Code analysis context
    │  └─ Multi-plan suffix
    │
    ├─ Generate 3 variants (LLM)
    ├─ Score each:
    │  ├─ minimal:       score=6/10
    │  ├─ standard:      score=8.5/10 ← BEST
    │  └─ comprehensive: score=7/10
    │
    └─ Output:
        {
          "agent": "PlannerAgent",
          "steps": [
            "1. Create Dockerfile with Node.js security best practices",
            "2. Create docker-compose.yml for multi-stage builds",
            "3. Create GitHub Actions workflow for CI/CD",
            "4. Add SAST scanning (Snyk/Trivy)"
          ],
          "required_artifacts": [
            "Dockerfile",
            "docker-compose.yml",
            "github_actions_workflow"
          ],
          "estimated_complexity": "medium",
          "reasoning_summary": "..."
        }

      ↓

[3] InfrastructureAgent.run()
    (ReAct Loop Iteration 1)

    ├─ Map infrastructure context
    ├─ Retrieve similar Dockerfile templates from RAG
    ├─ LLM call:
    │  System: "You are a DevSecOps engineer..."
    │  User: "Generate Dockerfile for: [plan]"
    │
    ├─ Parse LLM output → Extract artifacts
    │
    ├─ Evaluate quality:
    │  ├─ Dockerfile present? YES
    │  ├─ docker-compose present? YES
    │  ├─ Dockerfile valid? NO ✗
    │  │  └─ Issues: ["Missing HEALTHCHECK", "User not created"]
    │  └─ Return issues
    │
    │ (Issues found → Iteration 2)
    │
    (ReAct Loop Iteration 2)

    ├─ Refinement prompt appended:
    │   "=== REFINEMENT REQUEST (attempt 2) ===
    │    Your previous output had issues that MUST be fixed:
    │    • Missing HEALTHCHECK instruction
    │    • User not created for security
    │    Please regenerate with these fixes addressed."
    │
    ├─ LLM call (with refinement)
    ├─ Re-validate
    │  ├─ Dockerfile valid? YES ✓
    │  ├─ docker-compose valid? YES ✓
    │  └─ No critical issues
    │
    └─ Output:
        {
          "agent": "InfrastructureAgent",
          "artifacts": {
            "dockerfile": "FROM node:18-alpine...",
            "docker-compose": "version: '3.8'...",
            "github_actions_workflow": "name: CI/CD..."
          },
          "react_iterations": 2,
          "validation_summary": {
            "dockerfile": {
              "status": "valid",
              "issues": []
            },
            "docker-compose": {
              "status": "valid",
              "issues": []
            }
          }
        }

      ↓

[4] CICDAgent.run()
    ├─ Validate artifact contract
    ├─ Generate CI/CD manifest
    └─ Output: deployment configuration

      ↓

[5] Finalize
    ├─ Compile all results
    ├─ Set status: "completed"
    └─ Call TaskService.save()

      ↓

API Response:
{
  "id": "task-123",
  "status": "completed",
  "plan": {...},
  "result": {
    "artifacts": {...},
    "validation_summary": {...}
  },
  "logs": [
    {"step": "codebase_analysis", "message": "..."},
    {"step": "planner", "message": "..."},
    {"step": "infrastructure", "message": "..."}
  ]
}
```

---

## 5. Comment les Agents Communiquent

### Via State Object (LangGraph)

```python
@dataclass
class OrchestratorState:
    prompt: str
    repo_url: str | None

    # Phase outputs
    repository_analysis: dict | None = None
    plan: dict | None = None
    artifacts: dict | None = None
    validation_result: dict | None = None

    # Metadata
    status: str = "initialized"
    logs: list[dict] = field(default_factory=list)
    result: dict | None = None
```

**Flow réel:**
```python
# Dans OrchestratorAgent.run():

state = {
    "prompt": "...",
    "repo_url": "https://github.com/...",
    "status": "initialized"
}

# Step 1
state["repository_analysis"] = codebase_agent.run(
    repo_url=state["repo_url"],
    ...
)

# Step 2
state["plan"] = planner_agent.run(
    prompt=state["prompt"],
    planner_context=state["repository_analysis"].get("agent_context")
)

# Step 3
state["artifacts"] = infrastructure_agent.run(
    prompt=state["prompt"],
    plan=state["plan"],
    infrastructure_context=state["repository_analysis"].get("agent_context")
)

# Return final state
return state
```

---

## 6. Services de Support

### Infrastructure
- **GeminiChunkingService** → Chunking sémantique RAG
- **EmbeddingService** (Ollama) → Vecteurs pour RAG
- **QdrantService** → Vector database (knowledge base)

### Utilities
- **LLMService** → Appels Groq/Claude
- **ValidationService** → Validation artifacts (Dockerfile, YAML, HCL)
- **RepositoryParserService** → Analyse code
- **EnvSanitizerService** → Secrets detection
- **RepositoryRegistryService** → Cache analyses

### Database
- PostgreSQL w/ SQLAlchemy ORM
- Tables: tasks, task_logs, codebase_analysis, cicd_artifacts

---

## 7. Résumé Architecture

| Composant | Rôle | Type |
|-----------|------|------|
| **OrchestratorAgent** | Coordonne workflow | LangGraph state machine |
| **CodebaseAnalysisAgent** | Analyse repo | BaseAgent (standalone) |
| **PlannerAgent** | Génère plan | BaseAgent + LLM |
| **InfrastructureAgent** | Génère artifacts | EnhancedBaseAgent (ReAct loop) |
| **CICDAgent** | CI/CD pipeline | BaseAgent |
| **FastAPI Router** | HTTP REST API | /tasks endpoint |
| **TaskService** | Persistence | DB layer |
| **RAG Pipeline** | Template retrieval | Qdrant + Ollama |

---

## 8. Points Clés

✅ **Agents sont découplés** — chacun fait une tâche spécifique
✅ **Orchestration robuste** — LangGraph gère routing conditionnel
✅ **ReAct loop seulement sur InfrastructureAgent** — auto-refinement
✅ **Caching multi-niveaux** — memory + registry + RAG
✅ **Validation entre étapes** — artifacts QA

❌ **Agents ne partagent pas LLM** — chacun fait ses appels
❌ **Pas de feedback humain intégré** — todo
❌ **Concurrence non supportée** — sync-only

