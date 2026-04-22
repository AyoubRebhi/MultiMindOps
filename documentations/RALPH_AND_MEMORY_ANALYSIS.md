# RALPH Approach & Agent Memory System Analysis

## Q1: Is RALPH Being Used?

### What is RALPH?

**RALPH** = **Reasoning + Action + test Loop Handler**

A continuous autonomous coding approach where:
1. **Plan** → Break down task
2. **Code** → Generate artifacts
3. **Test** → Validate output
4. **Refine** → Iterate until completion
5. **Loop** → `while not complete: repeat(2-4)`

Used by Claude, Codex, CodeLLM for continuous code generation without human intervention.

---

## Answer: NO - This Project Does NOT Use RALPH ❌

### Current Architecture: LangGraph State Machine (Not RALPH Loop)

```python
# backend/app/agents/orchestrator_agent.py

self.graph = self._build_graph()

# Graph structure:
#
# START
#   ↓
# initialize (setup state)
#   ↓
# analyze_repository (CodebaseAnalysisAgent)
#   ↓
# planner (PlannerAgent)
#   ↓
# infrastructure (InfrastructureAgent)
#   ↓
# artifact_validation (ArtifactQualityValidator)
#   ↓
# cicd (CICDAgent)
#   ↓
# finalize (return results)
#   ↓
# END

# workflow.add_edge(START, "initialize")
# workflow.add_edge("initialize", "analyze_repository")
# workflow.add_edge("analyze_repository", "planner")
# ... etc
# workflow.add_edge("finalize", END)
```

### Why NOT RALPH?

| RALPH Characteristic | Current Project |
|----------------------|-----------------|
| **Continuous loop** `while True` | ❌ Linear graph (no loops) |
| **Code → Test → Refine** | ❌ Generate once, validate once |
| **Auto-retry on failure** | ❌ Manual human review required |
| **Autonomy** (no human input) | ❌ Human approval step (line 138-144) |
| **Iterative refinement** | ⚠️ ReAct loop in BaseAgent (not at workflow level) |

---

## What We HAVE Instead: LangGraph DAG + ReAct Loop

### 1. LangGraph State Machine (Orchestrator Level)

**Type:** Directed Acyclic Graph (DAG) - NOT a loop

```
Orchestrator.run()
┌──────────────────────────────────┐
│ 1. Analyze Repository            │ (Fetch + Security)
├──────────────────────────────────┤
│ 2. Planner                       │ (Generate plan)
├──────────────────────────────────┤
│ 3. Infrastructure                │ (Generate artifacts)
├──────────────────────────────────┤
│ 4. Validation                    │ (Check quality)
├──────────────────────────────────┤
│ 5. CI/CD                         │ (Generate pipelines)
├──────────────────────────────────┤
│ 6. Finalize                      │ (Save results)
└──────────────────────────────────┘

Each node runs ONCE, sequentially.
No retry loop at this level!
```

### 2. ReAct Loop (Agent Level, NOT Orchestrator)

**Location:** `BaseAgent.react_loop()` (base_agent.py, lines 92-227)

```python
# Inside EnhancedBaseAgent (used by InfrastructureAgent, etc)

for attempt in range(1, self.max_react_iterations + 1):  # max=3 iterations
    response = llm.chat_json(...)
    issues = evaluator(response)  # Check quality

    if not issues:
        RETURN response with confidence  # ✅ Success
    else:
        # Build refinement prompt (append issues)
        current_prompt = refinement_prompt  # Retry with same agent
```

**Scope:** Individual agents refining their OWN output (not orchestration level)

**Max retries:** 3 iterations per agent (not unlimited)

---

## Where RALPH Could Be: Task-Level Loop

### Current API Flow

```python
# backend/app/api/routes/tasks.py (lines 31-65)

@router.post("/", response_model=TaskResponse)
async def create_task(request: Request, db: Session = Depends(get_db)):
    payload, uploaded_env_input = await _parse_task_request(request)
    task = TaskService.create_task(db, payload.prompt)

    try:
        TaskService.update_task_status(db, task, "in_progress")

        orchestrator = OrchestratorAgent()
        workflow_state = orchestrator.run(...)  # ← 1 pass (not loop)

        # ... save results ...
        TaskService.update_task_status(db, task, "completed")

    except Exception as e:
        TaskService.save_error(db, task, str(e))
        # ❌ No auto-retry loop
```

**Issues:**
- ❌ No `while not_completed` loop
- ❌ Orchestrator runs once, returns
- ❌ Human approval required (line 138-144)
  ```python
  if workflow_state.get("result", {}).get("infrastructure", {}).get("artifacts"):
      TaskService.initialize_human_review(db, task)  # STOP for user approval
  ```
- ❌ No automatic refinement

---

## Q2: Where is Agent Memory Stored?

### Answer: IN-PROCESS JSON (NOT Qdrant)

---

## Memory Architecture

### 1. AgentMemory Class (memory.py)

**Location:** `backend/app/agents/memory.py`

```python
class AgentMemory:
    """
    Short-term memory for a single agent.

    Storage: IN-PROCESS (Python dict)
    Persistence: Optional JSON file
    TTL: Configurable expiry
    Capacity: Max 100 entries (default)
    """

    def __init__(
        self,
        agent_name: str,
        max_entries: int = 100,
        persist_path: Optional[str] = None,  # Optional file persistence
        ttl_seconds: Optional[float] = None,  # Time-to-live
    ):
        self._store: Dict[str, MemoryEntry] = {}  # ← In-process dict!
        self._decisions: List[DecisionRecord] = []  # ← In-process list!
```

### 2. Memory Storage Hierarchy

```
┌─────────────────────────────────────┐
│ AgentMemory (In-Process)            │          Tier 1: Session Memory
│  _store: {key → MemoryEntry}        │          (lives in RAM)
│  _decisions: [DecisionRecord]       │
└──────┬────────────────────────────┬─┘
       │ Optional persistence       │
       ↓                            ↓
    JSON File              (Future: Redis/DB)
    .json                  (Currently NOT used)
```

### 3. Memory Entry Structure

```python
@dataclass
class MemoryEntry:
    key: str                    # SHA256 hash of prompt
    agent_name: str             # "CodebaseAnalysisAgent"
    prompt: str                 # Original user prompt
    output: Dict[str, Any]      # LLM response
    confidence: float           # 0.0-1.0 (quality score)
    metadata: Dict[str, Any]    # Extra context
    timestamp: float            # Creation time
    access_count: int           # Times accessed

# Example:
{
  "key": "a1b2c3d4e5f6...32chars",
  "agent_name": "CodebaseAnalysisAgent",
  "prompt": "Analyze repo: /github.com/user/repo",
  "output": {
    "important_files": [...],
    "architecture": "..."
  },
  "confidence": 0.95,
  "timestamp": 1712668800.5
}
```

### 4. Memory Usage in Agents

```python
# backend/app/agents/base_agent.py (lines 84-88)

class EnhancedBaseAgent(BaseAgent):
    def __init__(self, name: str, max_react_iterations: int = 3):
        super().__init__(name=name)

        from backend.app.agents.memory import AgentMemory
        self.memory: AgentMemory = AgentMemory(agent_name=name)  # ← In-process!
```

### 5. Cache Hit Logic

```python
# base_agent.py - react_loop() method (lines 134-148)

for attempt in range(1, self.max_react_iterations + 1):

    # ── 1. Cache check (first attempt only) ────
    if attempt == 1:
        cached = self.memory.recall(user_prompt)  # ← Check in-process dict

        if cached and cached.confidence >= 0.7:  # ← Threshold: 70%
            logger.info("[%s] Cache hit — returning memorized output", self.name)
            return cached.output  # ← Return from memory (no LLM call!)
```

---

## Storage Comparison: Memory vs RAG vs Database

| Storage | Purpose | Technology | Lifetime |
|---------|---------|-----------|----------|
| **AgentMemory** | LLM prompt caching | In-process dict + optional JSON | Single session (~5-60 min) |
| **Qdrant (RAG)** | Repository knowledge chunks | Vector DB | Persistent (forever) |
| **SQLite/PostgreSQL** | Task history, analysis records | SQL DB | Persistent |

### NOT in Qdrant

Qdrant stores **semantic chunks for RAG retrieval**, not agent decisions:

```python
# What Qdrant stores:
{
  "id": "chunk_001",
  "path": "src/index.tsx",
  "content": "// Important file content...",
  "embedding": [0.23, -0.15, 0.45, ...],  # Vector
  "metadata": {"doc_type": "typescript"}
}

# What AgentMemory stores:
{
  "key": "a1b2c3d4...",
  "prompt": "Analyze this repo",
  "output": {"important_files": [...]}  # Not embedded
}
```

---

## Memory Persistence: Currently Minimal

### Optional JSON File Storage

```python
# memory.py (lines 234-244)

def _save(self) -> None:
    """Optionally persist to JSON file."""
    if self.persist_path is None:
        return  # ← DEFAULT: Not persisted!

    payload = {
        "agent_name": self.agent_name,
        "entries": {...},
        "decisions": [...]
    }
    self.persist_path.write_text(json.dumps(payload))  # JSON dump
```

**Currently:** NOT used (no persist_path configured)

```python
# How AgentMemory is initialized:
self.memory: AgentMemory = AgentMemory(agent_name=name)
# ↑ No persist_path argument = in-process only!
```

---

## Architecture Diagram: Memory vs Storage

```
┌─────────────────────────────────────────────────────────────┐
│ TASK REQUEST (User submits repo analysis)                  │
└────────────────┬────────────────────────────────────────────┘
                 │
    ┌────────────▼────────────┐
    │ OrchestratorAgent.run() │
    └────────────┬────────────┘
                 │
    ┌────────────▼──────────────────────┐
    │ CodebaseAnalysisAgent             │
    │                                    │
    │ self.memory = AgentMemory()        │  ← RAM-based
    │  ├─ recall(prompt)  ─check cache  │     in-process
    │  ├─ remember()      ─store result │
    │  └─ [100 entries:   max]          │
    │                                    │
    │ If cache hit: return cached       │  ← 0 LLM calls
    │ Else: run analysis                │  ← Standard flow
    └────────────┬──────────────────────┘
                 │
    ┌────────────▼────────────────────────┐
    │ Save to Registry (SQLite/Postgres)  │
    │ - analysis_output                   │
    │ - important_files                   │
    │ - execution_trace                   │
    └────────────┬─────────────────────────┘
                 │
    ┌────────────▼────────────────────┐
    │ Chunk & Embed (for RAG)          │
    │ Save to Qdrant                   │
    │ - Vector embeddings              │
    │ - Semantic search                │
    └─────────────────────────────────┘

Memory lifecycle:
├─ Session start: Create AgentMemory() [empty]
├─ First request: Cache miss → analyze → remember()
├─ Second request (same repo): Cache hit → return cached
└─ Session end: Delete all memory (no persist!)
```

---

## How to Add RALPH Loop? (Recommendations)

### Option 1: Task-Level Auto-Retry (Simple)

```python
# backend/app/api/routes/tasks.py

@router.post("/", response_model=TaskResponse)
async def create_task(request: Request, db: Session = Depends(get_db)):
    payload = ...
    task = TaskService.create_task(db, payload.prompt)

    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            orchestrator = OrchestratorAgent()
            workflow_state = orchestrator.run(...)

            validation = workflow_state.get("validation_summary", {})
            if validation.get("status") == "VALID":
                # ✅ Success
                break
            elif attempt < max_attempts - 1:
                # ⚠️ Failed, retry (simple RALPH loop)
                payload.prompt = _build_refinement_prompt(
                    payload.prompt,
                    validation.get("issues", [])
                )
                continue
        except Exception as e:
            if attempt < max_attempts - 1:
                continue  # Retry
            else:
                raise

    return task
```

### Option 2: Orchestrator Graph Loop (Complex)

Add cycle in LangGraph:

```python
def _build_graph(self):
    workflow = StateGraph(OrchestratorState)

    # ... add nodes ...

    # Add LOOP: infrastructure → validation → infrastructure
    def should_retry(state):
        validation = state.get("validation") or {}
        if validation.get("status") in ["PARTIAL", "INVALID"]:
            return "infrastructure"  # Loop back
        else:
            return "cicd"  # Continue forward

    workflow.add_conditional_edges(
        "artifact_validation",
        should_retry,
        {"infrastructure": "infrastructure", "cicd": "cicd"}
    )
```

### Option 3: Persistent Memory (Redis/DB)

```python
# Upgrade AgentMemory to cross-session

class AgentMemory:
    def __init__(self, agent_name, redis_url="redis://localhost:6379"):
        self.redis = redis.StrictRedis.from_url(redis_url)
        self.agent_name = agent_name

    def remember(self, prompt, output, confidence=1.0):
        key = self._hash(prompt)
        self.redis.setex(
            f"{self.agent_name}:{key}",
            ttl=3600*24,  # 24 hours
            value=json.dumps({"output": output, "confidence": confidence})
        )

    def recall(self, prompt):
        key = self._hash(prompt)
        data = self.redis.get(f"{self.agent_name}:{key}")
        return json.loads(data) if data else None
```

---

## Summary Table

| Aspect | Current | RALPH? | Location |
|--------|---------|--------|----------|
| **Workflow** | Linear DAG | ❌ No | Orchestrator (LangGraph) |
| **Retry Logic** | Up to 3x per agent | ⚠️ Partial | BaseAgent.react_loop() |
| **Auto-loop** | None at task level | ❌ No | tasks.py API |
| **Agent Memory** | In-process dict | ✅ Yes | memory.py (RAM) |
| **Persistent Memory** | Optional JSON | ❌ Unused | memory.py (no config) |
| **Knowledge Store** | Qdrant (RAG chunks) | ✅ Yes (for RAG) | qdrant_service.py |
| **Analysis Registry** | SQLite/Postgres | ✅ Yes | repository_registry_service.py |
| **Human Approval** | Required | ❌ Blocks autonomy | tasks.py line 138 |

