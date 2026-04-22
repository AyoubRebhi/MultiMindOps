# DevSecOps AI Platform - Workflow Architecture

## Table of Contents
1. [Vue d'ensemble](#vue-densemble-architecturale)
2. [Orchestrator Agent](#1-orchestrator-agent)
3. [Codebase Analysis Agent](#2-codebase-analysis-agent)
4. [Security Gate](#3-security-gate)
5. [Planner Agent](#4-planner-agent)
6. [Infrastructure Agent](#5-infrastructure-agent)
7. [Artifact Validation](#6-artifact-validation)
8. [Agent Memory](#7-agent-memory)
9. [CI/CD Agent](#8-cicd-agent)
10. [Data Flow](#flux-de-données-global)
11. [Key Decisions](#key-decisions--optimizations)

---

## Vue d'ensemble Architecturale

```
Orchestrator (LangGraph)
    ├─→ Initialize
    ├─→ Repository Analysis (CodebaseAnalysisAgent)
    ├─→ Security Gate (RepositorySecurityService)
    ├─→ Planner (PlannerAgent - Multi-plan)
    ├─→ Infrastructure Generation (InfrastructureAgent - ReAct + RAG)
    ├─→ Artifact Validation (ArtifactQualityValidator)
    ├─→ Artifact Filtering
    ├─→ CI/CD Generation (CICDAgent)
    └─→ Finalize
```

---

## 1. ORCHESTRATOR AGENT 📋

**Localisation:** `backend/app/agents/orchestrator_agent.py`

**Framework:** `LangGraph` (state machine multi-agent orchestrator)

**Rôle:**
- Coordonnateur principal du workflow DevSecOps
- Gère le routage dynamique basé sur le contexte (repository presence, security status, plan validity)
- Agrège les résultats de tous les agents
- Maintient le logging complet de chaque étape

### Entrées
```python
{
  "prompt": str,                    # La tâche utilisateur
  "repo_url": str | None,           # URL du repo à analyser
  "repository_visibility": str,     # 'public' | 'private'
  "github_token": str | None,       # Token pour clonage private repos
  "uploaded_env_input": dict | None # Variables .env uploadées
}
```

### Sorties
```python
{
  "status": "completed" | "partial_success" | "blocked" | "invalid",
  "repository_security": {...},     # Résultat du security gate
  "repository_analysis": {...},     # Analyse du codebase
  "plan": {...},                    # Plan généré
  "infrastructure": {...},          # Artefacts générés
  "cicd": {...},                    # Artefacts CI/CD
  "validation": {...},              # Résultats validation
  "logs": [{step, message}, ...]    # Trace complète
}
```

### Modes d'exécution
- `run()` - Full workflow (analysis → plan → generation → validation → cicd)
- `run_plan_preview()` - S'arrête après le planning (pour user review)
- `run_generation()` - Reprend après approbation artifacts par user

### Graph Topology
```
START
  │
  ▼
initialize
  │
  ├── (repo_url?) ──────────────────────────────┐
  │                                              ▼
  │                                    analyze_repository
  │                                              │
  │                          ┌───────────────────┤
  │                          │ security_blocked?  │ ok?
  │                          ▼                    ▼
  │                       finalize             planner ◄──── (no repo_url)
  │                                              │
  │                       ┌──────────────────────┤
  │                       │ empty_plan?           │ artifacts?
  │                       ▼                       ▼
  │                    finalize            infrastructure
  │                                              │
  │                                     artifact_validation
  │                                              │
  │                       ┌──────────────────────┤
  │                       │ fully_invalid?        │ ok / partial?
  │                       ▼                       ▼
  │                    finalize                 cicd
  │                                              │
  │                                           finalize
  │                                              │
  └──────────────────────────────────────────── END
```

**LLM utilisé:** ❌ Aucun direct (orchestration only - utilise 4 agents spécialisés)

---

## 2. CODEBASE ANALYSIS AGENT 🔍

**Localisation:** `backend/app/agents/codebase_analysis_agent.py`

**Framework:**
- GitHub API (GitHubService)
- LLM intelligent pipeline (OpenAI-compatible — LLaMA 3, Mixtral, Mistral via NVIDIA NIM / Groq / Together.ai)
- Qdrant vector DB (optional)
- Repository fingerprinting & caching

**Rôle:**
- Cloner et analyser le repository
- Scanner intelligent avec priorités (LLM-based file ranking)
- Détecter les fichiers critiques et architecture
- Extraction des variables d'environnement (.env)
- Construire le contexte pour les agents suivants

### Entrées
```python
{
  "repo_url": str,
  "repository_visibility": str,     # 'public' | 'private'
  "github_token": str | None,
  "uploaded_env": dict | None
}
```

### Pipeline interne
1. **Repository Fingerprint** - Identifier repo + commit SHA + branch
2. **Cache Decision** - Vérifier si analyse cached valide (unchanged/changed/new)
3. **Security Gate** - Run security scan (voir section SecurityGate)
4. **Intelligent Analysis** (si pas cachée):
   - QuickScannerService → détection rapide (file count, types, size category)
   - LLMPriorityEngine → LLM rank files par importance (OpenAI-compatible backend)
     - Smart token truncation pour repos >200 fichiers (critical files toujours préservés)
     - Heuristic fallback si LLM call échoue
   - TargetedRepositoryParser → Parse uniquement fichiers critiques
5. **Heuristic Parser** - Parse tous les fichiers (fallback si intelligent fails)
6. **Context Building** - Extrait infrastructure needs, services, entrypoints
7. **Env Detection** - Détecte .env files, sanitize variables sensibles, compute fingerprint

### Sorties
```python
{
  "repo_summary": {...},
  "file_tree": [...],
  "important_files": [...],         # Ranked par LLM
  "key_entrypoints": [...],
  "categorized_files": {
    "backend_files": [],
    "frontend_files": [],
    "deployment_files": [],
    "ci_cd_files": [],
    ...
  },
  "chunks": [...],                  # Code chunks avec metadata
  "agent_context": {
    "planner_context": {...},       # Pour PlannerAgent
    "infrastructure_context": {...}
  },
  "env_security_runtime": {
    "sensitive_values": [...],
    "all_values": [...]
  },
  "repository_analysis": {
    "cache_status": "reused|new_analysis|recomputed_after_change",
    "decision": {...},
    "identity": {...},
    "record_id": str
  }
}
```

### Cache Strategy
- **Hash:** Normalized URL + branch + commit SHA
- **Fingerprint:** Content hash des fichiers importants
- **TTL:** Recompute si commit change OU env files change
- **Status tracking:** cache_status logs dans les records

**LLM utilisé:**
- ✅ `LLMClient` (LLMPriorityEngine) — OpenAI-compatible endpoint, configurable via env vars:
  - `LLM_API_KEY` — provider API key (fallback: `GROQ_API_KEY`)
  - `LLM_BASE_URL` — endpoint base URL (default: `https://api.groq.com/openai/v1`)
  - `LLM_MODEL` — model identifier (default: `llama3-70b-8192`)
  - Compatible providers: NVIDIA NIM, Groq, Together.ai, OpenAI
  - Compatible models: `meta-llama/Llama-3-70b-instruct`, `mistralai/Mixtral-8x7B-Instruct-v0.1`, `llama3-70b-8192`
  - Temperature: `0.1` (deterministic), timeout: 60s, max retries: 2
- ✅ Optional: Qdrant vector retrieval pour context enrichment

---

## 3. SECURITY GATE 🛡️

**Localisation:** `backend/app/services/repository/repository_security_service.py`

**Framework:** `RepositorySecurityService` (static/heuristic scanning)

**Rôle:**
- Scanner de sécurité précoce
- Détecte repos malveillants/suspects/sensibles
- Analyse credentials leakage, disallowed patterns
- Block → Finalize immédiatement (pas de progression)

### Entrées
```python
{
  "repo_url": str,
  "repo_path": str  # Path to cloned repository
}
```

### Sorties
```python
{
  "status": "safe" | "safe_with_warnings" | "blocked",
  "warnings": [str, ...],          # Non-blocking concerns
  "blocked_reasons": [str, ...]    # Blocking factors
}
```

### Logique de routage
```python
if security_status == "blocked":
  # Skip planner + infrastructure
  # Go directly to finalize with blocked status
  next_step = "finalize"
else:
  # Continue to planner
  next_step = "planner"
```

**LLM utilisé:** ❌ Aucun (static heuristics)

---

## 4. PLANNER AGENT 🎯

**Localisation:** `backend/app/agents/planner_agent.py`

**Framework:**
- Pydantic (validation schemas)
- AgentMemory (caching)
- Multi-plan generation (3 variants scored)

**Rôle:**
- Générer le plan d'exécution DevSecOps
- Proposer 3 variantes (minimal/standard/comprehensive)
- Scorer chaque variante sur 4 axes indépendants
- Sélectionner la meilleure automatiquement
- Rappeler les plans précédents (memory cache)

### Entrées
```python
{
  "prompt": str,
  "planner_context": {
    "project_type": str,
    "important_files": [...],
    "key_entrypoints": [...],
    ...
  }
}
```

### Multi-plan Generation Process
1. **System prompt expansion** -  Base prompt + suffix spécifique "Generate 3 plan variants..."
2. **LLM call** - Demander Claude générer JSON avec 3 `PlanVariant`
3. **Parse response** - Validate via Pydantic `MultiPlanResponse`
4. **Score each plan** sur 4 axes:
   ```
   Total Score (0-2.0 scale):
   ├─ Artifact coverage (0-0.6)    → 0.1 per artifact, max 6
   ├─ Step quality (0-0.5)          → 0.1 per step, max 5
   ├─ Reasoning depth (0-0.5)       → proportional to summary length
   └─ Complexity fit (0-0.4)        → "medium"=0.4, "low"/"high"=0.2
   ```
5. **Select winner** - Highest score variant
6. **Store alternatives in memory** pour debugging + decision log

### Sorties
```python
{
  "agent": "PlannerAgent",
  "input_prompt": str,
  "steps": [str, ...],                           # Ordered execution steps
  "required_artifacts": [str, ...],              # Ex: ["Dockerfile", "docker-compose.yml"]
  "estimated_complexity": "low|medium|high",
  "reasoning_summary": str,
  "plan_variant": "minimal|standard|comprehensive",
  "plan_score": float,                           # 0-2.0
  "plan_description": str,                       # One-liner for this variant
  "plan_alternatives": [
    {
      "variant": str,
      "score": float,
      "description": str,
      "required_artifacts": [...],
      "estimated_complexity": str
    }
  ]
}
```

### Plan Variant Definitions
- **minimal** - Only essential artifacts to run project
- **standard** - Recommended balanced approach (DEFAULT selected)
- **comprehensive** - Full coverage (monitoring, security scans, IaC)

### Memory Caching
- **Cache key:** SHA256(prompt + planner_context)
- **TTL:** Session-based (24h optional)
- **Hit criteria:** confidence >= 0.7
- **Fallback:** If cache miss, execute multi-plan

### Dynamic Routing après Planner
```python
if not required_artifacts and not reasoning and not steps:
  # Empty plan detected
  next_step = "finalize"  # Skip infrastructure
else:
  # Proceed to infrastructure generation
  next_step = "infrastructure"
```

**LLM utilisé:**
- ✅ Claude (ou OpenAI compatible)
- **Température:** 0.3 (semi-deterministic)
- **Max tokens:** 2200
- **Mode:** `chat_json` - enforces JSON response

---

## 5. INFRASTRUCTURE AGENT 🏗️

**Localisation:** `backend/app/agents/infrastructure_agent.py`

**Framework:**
- `EnhancedBaseAgent` (inherit ReAct loop + memory + validation)
- LLMService (multi-turn LLM)
- Qdrant RAG (template retrieval + semantic search)
- ValidationService (Dockerfile validation, docker-compose check, etc.)
- AgentMemory (cache full responses)

**Rôle:**
- Générer artefacts infrastructure DevSecOps
- Quality loop (ReAct - Reasoning + Action with feedback)
- Template retrieval via RAG sémantique
- Fallback deterministic artifacts si generation fails
- InfrastructureArtifactBuilderService pour construcciones déterministes

### Entrées
```python
{
  "prompt": str,
  "plan": {...},                    # From PlannerAgent
  "infrastructure_context": {       # From CodebaseAnalysisAgent
    "project_type": str,
    "services": [...],
    "runtime": {...},
    "sanitized_env_context": {...},
    "artifact_targets": {...},
    "artifact_expectations": {...}
  },
  "approved_artifacts": [str]       # Subset de required_artifacts
}
```

### Exécution Pipeline
1. **Map context** → InfrastructureContextMapper
2. **Build fallback artifacts** → Deterministic defaults (InfrastructureArtifactBuilderService)
3. **RAG retrieval** (Qdrant primary, ChromaDB fallback)
4. **Build compact prompts** (reduce token usage)
5. **ReAct loop** (up to 3 iterations with quality feedback)
6. **Artifact selection** (generated vs. fallback)
7. **Artifact-level validation** → ValidationService.validate_artifacts()

### Sorties
```python
{
  "artifacts": {
    "dockerfile": str,
    "docker_compose": str,
    "kubernetes_deployment": str,
    "terraform_main": str,
    ...
  },
  "generated_artifacts": [str],
  "rag": {
    "enabled": bool,
    "available": bool,
    "template_ids_used": [str],
    "generated_with_rag": bool,
    "fallback_used": bool,
    "fallback_reasons": {...}
  },
  "react_iterations": int,          # 1-3
  "validation_summary": {...},
  "context_used": {...}
}
```

**LLM utilisé:**
- ✅ Claude (temperature 0.2, max 2200 tokens)
- Iterations: Up to 3 (ReAct)

---

## 6. ARTIFACT VALIDATION ✅

**Localisation:** `backend/app/services/cicd/artifact_quality_validator.py`

**Framework:** `ArtifactQualityValidator` + `ValidationService`

**Rôle:**
- Valider qualité et complétude des artefacts
- Checker against required_artifacts list
- Quality checks (syntax, generic content, etc.)

### Sorties
```python
{
  "status": "valid|partial|invalid",
  "required_artifacts": [str],
  "generated_artifacts": [str],
  "missing_artifacts": [str],
  "quality_issues": [str],
  "warnings": [str],
  "artifact_statuses": [{...}]
}
```

**Dynamic Routing après validation:**
```python
if status == "invalid" AND all_required_missing:
  next_step = "finalize"  # Skip CI/CD
else:
  next_step = "cicd"      # Proceed (valid or partial)
```

**LLM utilisé:** ❌ Aucun

---

## 7. AGENT MEMORY 🧠

**Localisation:** `backend/app/agents/memory.py`

**Framework:** `AgentMemory` (in-memory dictionary + optional file persistence)

**Rôle:**
- Cache prompt → output per agent
- Decision logging (structured records)
- TTL eviction + capacity management

### Features
- **Prompt caching:** SHA256(prompt) → cached output
- **Confidence scoring:** 0-1 scale (used for eviction)
- **Decision history:** Structured records with reasoning
- **Persistence:** Optional JSON file
- **TTL expiry:** Optional time-based eviction

### Memory Entry Model
```python
@dataclass
class MemoryEntry:
  key: str                    # SHA256(prompt)[:32]
  agent_name: str
  prompt: str
  output: Dict[str, Any]
  confidence: float           # 0-1
  metadata: Dict[str, Any]
  timestamp: float
  access_count: int
```

### Usage
```python
memory = AgentMemory("PlannerAgent", max_entries=100)
memory.remember(prompt, plan_output, confidence=0.9)
cached = memory.recall(prompt)  # Returns MemoryEntry or None
```

**Utilisé par:**
- `PlannerAgent` - Cache plans per prompt
- `InfrastructureAgent` - Cache full responses
- Extensible pour tous les agents

**LLM utilisé:** ❌ Aucun

---

## 8. CI/CD AGENT 🚀

**Localisation:** `backend/app/agents/cicd_agent.py`

**Framework:**
- `CicdHandoffService` - Normalise le contrat upstream
- `CicdWorkflowBuilderService` - Builder déterministe pour workflows
- `GitHubActionsTemplateService` - Charge templates locaux (`/rag/corpus/cicd/`)
- `RAGPipelineService` - Retrieval sémantique (Qdrant) pour enrichissement
- `CicdContractValidationService` - Valide contrats sortants

**Rôle:**
- Générer workflows GitHub Actions adaptés au runtime
- Détecter automatiquement langage + framework
- Adapter les étapes (Build, Test, SAST, Security Scans)
- Normaliser artifact statuses
- Préparer handoff pour déploiement
- **Never executes** - artifact generation only

### Détection Runtime & Adaptation 🔍

Le service détecte le runtime et sélectionne les templates appropriés:

```python
detect_project_runtime(normalized_handoff):
  ├─ Python → python_ci.yml (fallback simple) ou full_stack_ci_cd.yml (RAG)
  ├─ Node.js → node_ci.yml
  ├─ Java (Spring Boot) → spring_boot_ci.yml
  ├─ Dockerized → docker_build.yml
  └─ Generic → docker_build.yml (fallback)
```

### Exécution Pipeline
1. **Normalize handoff** - Standardiser contrat upstream
2. **Detect runtime** - Analyser `repo_summary`, `runtime.languages`, `frameworks`, entrypoints
3. **RAG retrieval** - Query: `"github actions ci cd workflow {language} {framework} security scan"`
   - Primary: Qdrant vector DB (hybrid search, top_k=3)
   - Fallback: LocalFileService templates
4. **Select template** - Match runtime + Dockerized status
5. **Generate workflows** - Charge contenu template ou fallback déterministe
6. **Merge statuses** - Keep upstream non-CI/CD, replace CI/CD statuses
7. **Validate output** - CicdContractValidationService

### Templates Disponibles 📋

#### Simples (Déterministes - Fallback)
```yaml
# Étapes de base:
├─ Checkout source
├─ Setup runtime (Python 3.11, Node 20, Java 17)
├─ Install dependencies (pip/npm/maven)
└─ Run tests (unittest/npm test/mvn test)

# Fichiers:
├─ python_ci.yml - Python tests
├─ node_ci.yml - Node.js tests + lint
├─ spring_boot_ci.yml - Maven build + test
└─ docker_build.yml - Docker build (sans push)
```

#### Avancés (RAG - Sécurité Intégrée)
```yaml
# Étapes complètes DevSecOps:
├─ Tests & Lint (pytest, ruff, mypy)
├─ SAST (Semgrep, CodeQL)
├─ Dependency Scan (Gitleaks, OWASP Dependency-Check, Safety)
├─ Build & Container Scan (Docker Buildx + Trivy)
└─ Push to Registry (AWS ECR avec OIDC, pas secrets long-lived)

# Fichier:
└─ full_stack_ci_cd.yml - Pipeline complet avec scans sécurité
```

### Étapes du Workflow (Full Stack) 🔒

| # | Étape | Outil(s) | Trigger |
|---|-------|---------|---------|
| 1 | **Test & Lint** | `pytest`, `ruff`, `mypy` | Tous les pushes/PRs |
| 2 | **SAST** | `Semgrep`, `CodeQL` | Tous les pushes/PRs |
| 3 | **Dependency Scan** | `Gitleaks`, `OWASP Dependency-Check`, `Safety` | Tous les pushes/PRs |
| 4 | **Build & Container Scan** | `Docker Buildx`, `Trivy` | Après Test + SAST |
| 5 | **Push to Registry** | `AWS ECR` (OIDC auth) | `main` branch only |

**Sécurité:** Secrets via `${{ secrets.* }}` + OIDC (pas de long-lived keys)

### Sorties
```python
{
  "agent": "CICDAgent",
  "prototype_scope": "artifact_generation_only",
  "generated_artifacts": [str],                # [".github/workflows/ci-cd.yml"]
  "artifact_statuses": [
    {
      "path": str,                             # ".github/workflows/ci-cd.yml"
      "group": "cicd",
      "status": "generated|missing|placeholder",
      "required": bool,
      "source": "generated|planned"
    }
  ],
  "artifacts": {
    ".github/workflows/ci-cd.yml": str,       # YAML workflow content
    ".github/workflows/security-scan.yml": str # Si RAG disponible
  },
  "handoff_context": {
    "detected_runtime": {
      "language": "Python|Node.js|Java|generic",
      "framework": "FastAPI|Express|Spring Boot|generic",
      "package_manager": "pip|npm|maven",
      "dockerized": bool
    },
    "artifact_statuses": [...]
  },
  "validation": {
    "status": "valid|invalid",
    "diagnostic": {
      "generated_count": int,
      "missing_count": int
    }
  },
  "readiness_summary": str,
  "notes": [str, ...]
}
```

### Fallback Strategy 🔄

Si RAG template non disponible:
```python
if not template or template.content.empty:
  # Use deterministic fallback based on runtime
  if runtime == "python":
    return _build_python_fallback()
  elif runtime == "node":
    return _build_node_fallback()
  elif runtime == "java":
    return _build_java_fallback()
  elif dockerized:
    return _build_docker_fallback()
  else:
    return ""  # missing
```

**LLM utilisé:**
- ✅ RAG templates only (semantic retrieval - no LLM generation)
- ❌ No direct Claude/OpenAI LLM calls
- ✅ Local template service (deterministic fallback)

---

## Flux de Données Global

```
User Input
    ↓
[Orchestrator] START → [CodebaseAnalysis] → [SecurityGate]
    ├─ BLOCKED → [Finalize] → END
    └─ SAFE → [Planner] → generate 3 variants, score, select
        ├─ Empty plan? → [Finalize] → END
        └─ Has artifacts? → [Infrastructure]
            ├─ RAG retrieval (Qdrant ↔ ChromaDB)
            ├─ ReAct loop (0-3 iterations)
            └─ Generate artifacts
                ↓
            [Artifact Validation]
            ├─ Check completeness
            ├─ All required missing? → [Finalize] → END (invalid)
            └─ Valid or partial? → [CI/CD Agent]
                ├─ Detect runtime
                ├─ RAG retrieval (GitHub Actions)
                └─ Generate workflows
                    ↓
                [Finalize]
                ├─ Build final contract
                ├─ Aggregate validations
                └─ END (success|partial|blocked|invalid)
```

---

## Key Decisions & Optimizations

1. **Dynamic Routing** - Skip steps si conditions non remplies
2. **ReAct Loop** - Iterate jusqu'à qualité acceptable (max 3 tries)
3. **RAG Semantic** - Templates via Qdrant, fallback déterministe
4. **Memory Caching** - Prompt hash → cached output (24h TTL)
5. **Multi-plan** - 3 variants générées, scored automatiquement
6. **Environment Handling** - Detection, sanitization, tracing
7. **Artifact Filtering** - User approval subset avant generation
8. **Execution Tracing** - Full audit trail per step

---

## Résumé Comparatif

| Composant | Framework | LLM | Itérations |
|-----------|-----------|-----|-----------|
| **Orchestrator** | LangGraph | ❌ | 1 |
| **CodebaseAnalysis** | GitHub + LLMClient (OpenAI-compat) | ✅ | 1 |
| **SecurityGate** | Custom service | ❌ | 1 |
| **Planner** | Pydantic + Memory | ✅ Claude | 1 (3 cached) |
| **Infrastructure** | ReAct + RAG | ✅ Claude | 1-3 (ReAct) |
| **Validation** | Custom validator | ❌ | 1 |
| **AgentMemory** | In-memory dict | ❌ | - |
| **CICD** | Handoff + RAG | ✅ RAG only | 1 |
