# FINAL RELEASE-CANDIDATE E2E VALIDATION REPORT

**Role:** Senior Platform QA Engineer
**Run:** Run 2 — full-environment run (Docker Desktop, Qdrant, and MCP server all started)
**Date:** 2026-06-11
**Branch:** `dev`
**Code modified during test:** **None** (read-only execution + DB inspection; git tree identical to pre-run snapshot)

> Run 1 (earlier, same day) executed with **Docker daemon down, Qdrant down, MCP down**. This Run 2 was requested after the operator started all three integrations. Where Run 2 contradicts Run 1, Run 2 is authoritative.

---

## TEST INPUT

| Field | Value |
|---|---|
| Prompt | `Deploy my project` |
| Repository | https://github.com/AyoubRebhi/devopsTP (Java 17 / Spring Boot) |
| Plan | balanced |
| Approval mode | manual approval at every phase (each phase invoked explicitly) |

**Identifiers (this run):**
- `project_id` = `ff0799ab-c5d9-459c-a53d-8ade3c5e0c91`
- `workflow_id` = `4cb829ed-264e-40db-84c7-6663b44816be`
- `task_id` = `26186f93-72f4-4dc9-b2cb-30ab4511f3fa`
- sanitized `project_name` = `f93-72f4-4dc9-b2cb-30ab4511f3fa` (31 chars)
- docker image tag = `youbi2012m/analyze-the-connected-repository:26186f93-1781168570`

**Runtime environment:**
| Component | Status |
|---|---|
| PostgreSQL | 17.9 — up ✓ |
| Terraform CLI | v1.15.5 ✓ |
| **Docker daemon** | **server 29.5.2 — reachable ✓** (was down in Run 1) |
| **Qdrant** | **up ✓** — collection `devsecops_kb` present |
| **MCP server** | **loaded ✓** — `[MCPClient] … (direct mode, mcp=true)` |
| LLM — OpenAI primary | key present, but **rate-limited** (`rate_limit_exceeded`, tokens) during Docker phase |
| LLM — Groq fallback (6 keys) | present, **all rate-limited** (TPM 12000 < 14179 requested) |
| AWS credentials | present ✓ (terraform plan reaches AWS) |

---

## 1. EXECUTION SUMMARY

| Step | Phase | Result | Note |
|---|---|---|---|
| 1 | System readiness | ✅ PASS | All endpoints present; legacy absent; Docker+Qdrant+MCP up |
| 2 | Project + workflow creation | ✅ PASS | Exactly 1 workflow / 1 task |
| 3 | Analysis | ✅ PASS | security=safe, risk=2, 3 plans, recommend=balanced |
| 4 | Plan selection (balanced) | ✅ PASS | `PLAN_SELECTED=completed`, `selected_plan_id=balanced` |
| 5 | Terraform generation | ✅ PASS | 6 DB artifacts; names start-with-letter ✓ |
| 6 | Terraform validation | ✅ PASS | `ok=true` (validate does not check name length) |
| 7 | **Terraform plan** | ❌ **FAIL** | **ALB/TG resource names exceed AWS 32-char limit** |
| 8 | Docker generation | ⚠️ PASS w/ fallback | 4 DB artifacts; HEALTHCHECK valid, **but body unbuildable** |
| 9 | **Docker build** | ❌ **FAIL** | **`mvn: not found` — JRE base image, no Maven (generation defect)** |
| 10 | Replay | ✅ PASS | Deterministic, LLM-free; reproduces every PASS *and* FAIL |
| 11 | Observability | ⚠️ PARTIAL | Completeness truthful; **plan-failure not classified** |
| 12 | State consistency | ✅ PASS | 1 active workflow, no dup phases, phases_state authoritative |

**Endpoints (STEP 1):** `/openapi.json` 200 ✓ · `…/workflows/{id}/debug` ✓ · `…/workflows/{id}/replay` ✓ · `/api/execution/docker/health` ✓ (`reachable=true`, server 29.5.2). **Legacy absent:** no `/workflow/run*`, no `/terraform/generate`. Boot note (non-fatal, pre-existing data): `WORKFLOW_GUARD` skips the single-active unique index because 6 legacy projects already have multiple active workflows; the app-level `get_or_create` guard still prevents new duplicates (verified in STEP 12).

---

## 2. ARTIFACT AUDIT

**11 artifacts persisted to DB** (cross-checked: `/debug` `persisted_count=11` == DB count). Fewer than Run 1's 13 because the **failed plan produced no `plan.json` / `infrastructure_summary`**.

| type | subtype | val_status | bytes |
|---|---|---|---|
| terraform | terraform_main | pending | 7064 |
| terraform | terraform_variables | pending | ~2153 |
| terraform | terraform_providers | pending | 596 |
| terraform | terraform_tfvars | pending | 450 |
| terraform | terraform_outputs | pending | 833 |
| terraform | terraform_backend | pending | 188 |
| docker | dockerfile | pending | 349 |
| docker | docker_compose | pending | ~543 |
| docker | dockerignore | pending | ~54 |
| docker | env_example | pending | ~75 |
| validation_report | terraform_validation.json | passed | — |

All `artifact_type` / `artifact_subtype` correct; canonical `terraform_*` subtypes preserved; **DB-first** confirmed (validation/plan/build/replay all rehydrated from DB — `[TerraformPipelineService] Rehydrated artifact …`). No filesystem-only dependency.

---

## 3. TERRAFORM REPORT

**Generation:** PASS — 6 files (`monolith/balanced` template). Inline init/validate during generation again reported `degraded / NETWORK_ERROR` (same as Run 1) **even though the registry was reachable** (the dedicated validation phase downloaded the AWS provider fine). Non-blocking: artifacts persisted DB-first. `backend.tf` emitted as a dev placeholder (TF_STATE_* env unset — expected in dev).

**Validation:** PASS — DB rehydration used; `terraform validate` ⇒ `ok=true`. Note: `terraform validate` does **not** validate resource-name length, so it cannot catch the defect below.

**Plan:** ❌ **FAIL** — `result_summary.ok=false`, phase node `status=failed`, `error="terraform reported a non-zero exit — see logs"`. Reproduced independently in the rehydrated working dir (exit code 1):

```
Error: "name" cannot be longer than 32 characters: "f93-72f4-4dc9-b2cb-30ab4511f3fa-alb"
  with aws_lb.main, on main.tf line 135, in resource "aws_lb" "main"

Error: "name" cannot be longer than 32 characters
  with aws_lb_target_group.app, on main.tf line 143, in resource "aws_lb_target_group" "app"
```

**Resource-name audit** (prefix `f93-72f4-4dc9-b2cb-30ab4511f3fa`, 31 chars — starts with letter `f` ✓, lowercase ✓, `[a-z0-9-]` ✓):

| Resource | Resolved name | Len | AWS limit | Verdict |
|---|---|---|---|---|
| `aws_lb` | `…-alb` | **35** | 32 | ❌ **EXCEEDS** |
| `aws_lb_target_group` | `…-tg` | **34** | 32 | ❌ **EXCEEDS** |
| `aws_db_instance` (id) | `…-db` | 34 | 63 | ✓ |
| `aws_db_subnet_group` | `…-db-subnet` | 41 | 255 | ✓ |
| `aws_ecs_cluster` | `…-cluster` | 39 | 255 | ✓ |
| `aws_ecs_service` | `…-service` | 39 | 255 | ✓ |
| `aws_iam_role` | `…-ecs-task-execution` | 50 | 64 | ✓ |
| security groups (×3) | `…-alb-sg` / `…-ecs-tasks-sg` / `…-rds-sg` | 38–44 | 255 | ✓ |

> `variables.tf` carries `validation { condition = can(regex("^[a-z][a-z0-9-]{0,31}$", var.project_name)) }`. This enforces the *project_name* is ≤32 and starts with a letter, but **reserves no headroom for resource suffixes** (`-alb` +4, `-tg` +3). Any sanitized name ≥ 29 chars overflows the ALB limit.

---

## 4. DOCKER REPORT

**Generation:** PASS with deterministic fallback (`completed_with_fallback`, 86s, 4 artifacts). Cause (environmental): OpenAI `rate_limit_exceeded`, then all 6 Groq keys exhausted → `[LLMService] All keys exhausted` → fallback. Phase did **not** 500 (non-raising contract honored).

Generated Dockerfile (349 B):
```dockerfile
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY TP-Projet/pom.xml .
RUN mvn dependency:go-offline -q          # <-- mvn not present in a JRE image
RUN groupadd -r appgroup && useradd -r -m -g appgroup appuser
COPY --chown=appuser:appgroup . .
RUN mkdir -p /app/logs /app/tmp && chown -R appuser:appgroup /app
USER appuser
EXPOSE 8080
HEALTHCHECK NONE
CMD ["java", "-jar", "app.jar"]
```

**Dockerfile quality findings:**
- ✅ **HEALTHCHECK valid** (`HEALTHCHECK NONE` — sanitizer's safe default); **no literal `\n` escapes; no malformed instructions** → goal #6 exercised and clean.
- ✅ Runtime-permission hardening present (non-root `appuser`, `COPY --chown`, pre-`USER` `mkdir`+`chown`).
- ❌ **Semantically unbuildable:** base `eclipse-temurin:17-jre` has no Maven/JDK, yet `RUN mvn …` is invoked; no `mvn package` step produces `app.jar`.
- ⚠️ **Non-deterministic generation:** Run 1 (same repo) produced a *correct multi-stage* Maven→JRE Dockerfile; Run 2 produced this *broken single-stage* one. The "fallback" output quality varies run-to-run (consistent with partial per-section LLM assembly under rate-limiting).

**Build:** ❌ **FAIL** — and this time the **daemon was up, so the build genuinely executed** (proves Docker connectivity works end-to-end):
```
#0 building with "desktop-linux" instance using docker driver
#2 load metadata for docker.io/library/eclipse-temurin:17-jre   DONE
#5 [1/7] FROM eclipse-temurin:17-jre                            DONE
#6 transferring context: 48.64kB                                DONE
#7 [2/7] WORKDIR /app                                           CACHED
#9 [4/7] RUN mvn dependency:go-offline -q
   /bin/sh: 1: mvn: not found
   ERROR: process "/bin/sh -c mvn dependency:go-offline -q" did not complete successfully: exit code: 127
docker build exited with code 1
```
Workflow auto-routed to `human_review_required` (corrector) ✓. **Classification: generation defect** (broken Dockerfile), NOT a daemon/repository/workflow issue. The `docker_connectivity` fix is confirmed working (context transfer, metadata pull, build steps all ran).

---

## 5. REPLAY REPORT

- **Mode:** `read_only_db_artifacts` · **`llm_used=false`** · **`regenerated=false`** · `replayed=true` · 0 skipped.
- **Deterministic:** ✅ — reproduces every original outcome, including the failures:

| Phase | Original (live) | Replay | Match |
|---|---|---|---|
| TERRAFORM_VALIDATION | ok=true | ok=true | ✅ |
| TERRAFORM_PLAN | ok=false (name >32) | ok=false (name >32) | ✅ |
| DOCKER_BUILD | failed (mvn) | failed (mvn) | ✅ |

- **Replay trace appended:** ✅ — execution trace = 10 entries (7 `source=live` + 3 `source=replay`); live history preserved.
- **Drift detected:** **NONE.** Replay determinism holds for both success and failure paths (strong evidence for goal #8).

---

## 6. OBSERVABILITY REPORT

- **Timeline:** complete — all phases present; live trace correctly shows `TERRAFORM_PLAN failed` and `DOCKER_BUILD failed`.
- **Trace:** complete — 10 `/debug` entries == 10 persisted `workflow_execution_traces` rows; `source` distinguishes live vs replay.
- **Completeness:** ✅ **truthful** — `complete=true`, `persisted_count=11`, `persisted_terraform_count=6`, `missing_keys=[]` (accurate: all *expected artifacts* exist; completeness is about presence, not phase success).
- ⚠️ **Classification gaps (defect):**
  - `terraform_status.terraform_failure_classification = NETWORK_ERROR` — this is the **stale generation-time** classification. The *actual* plan failure (AWS name length) is **not classified** and **not present** in `failure_classifications` (which only lists the generation NETWORK_ERROR). An operator reading the status would mis-attribute the plan failure to a network problem.
  - Docker build `failure_reason` = `"View build details: docker-desktop://…"` (a buildx dashboard URL) instead of the meaningful `mvn: not found / exit 127`; `failure_classification=null`, `failed_step=null`. The real error is only in the raw log lines.

---

## 7. CRITICAL ISSUES (runtime-verified only)

### 🔴 HIGH

**H-1 — Terraform plan fails: ALB/Target-Group names exceed AWS 32-char limit.**
`sanitize_terraform_name` caps `project_name` at 32 chars but reserves no budget for resource suffixes, so `${project_name}-alb` (+4) and `${project_name}-tg` (+3) overflow. `project_name` derives from the task UUID, which after stripping only leading digits is typically 30–35 chars ⇒ the ALB name almost always exceeds 32. **Run 1 passed only by luck** (its UUID had 8 strippable leading digits → 27-char name). `terraform validate` does not catch it; `terraform plan` fails deterministically with exit 1. Breaks a core deliverable for the majority of inputs. *Directly regresses validation goals #4 (plan) and #5 (name sanitization).*

**H-2 — Docker fallback produces an unbuildable Dockerfile for Java/Maven.**
Under LLM rate-limiting the generation emitted a single-stage Dockerfile with a **JRE base image (`eclipse-temurin:17-jre`) but a `mvn` build command** and no jar-producing step. The build fails at `RUN mvn …` (`mvn: not found`, exit 127). Output is **non-deterministic** (Run 1's fallback was a correct multi-stage build). The deterministic safety-net is supposed to be reliable; here it produced a guaranteed-failing artifact.

### 🟠 MEDIUM

**M-1 — RAG knowledge collection mismatch (Qdrant up but unused).** The RAG pipeline queries collection **`devsecops_knowledge`** → `Collection … non trouvée`. `.env` sets `RAG_COLLECTION_NAME=infra_templates`; the only collection present is **`devsecops_kb`**. Three different names ⇒ RAG retrieval degrades to empty context even with Qdrant running, so generation gets no knowledge grounding.

**M-2 — RDS engine/version/port mismatch (carried from Run 1, still present).** `terraform.tfvars` sets `db_engine="mysql"`, but `main.tf` hardcodes `engine_version="15"` (a PostgreSQL major) and the RDS security group opens **port 5432** (Postgres), not 3306. Passes `validate`; would fail at `apply`.

**M-3 — Failure classification gaps (observability).** The terraform plan naming failure is unclassified and absent from `failure_classifications`; `terraform_status` surfaces a stale `NETWORK_ERROR`; the Docker `failure_reason` is a dashboard URL rather than the real error. Reduces diagnosability of exactly the failures that occurred.

### 🟡 LOW

- **L-1** — Generation-phase inline terraform init/validate reports `NETWORK_ERROR` even when the registry is reachable (both runs); harmless (dedicated validation phase succeeds) but pollutes `terraform_status`.
- **L-2** — `ARCHITECTURE_DECISION` phase node stays `awaiting_input` after the workflow advances (cosmetic; progression tracked via `PLAN_SELECTED`).
- **L-3** — `workflow.current_phase` (`DOCKER_BUILD`) vs `task.current_phase` (`human_review_required`) divergence (separate trackers; `phases_state` remains authoritative).
- **L-4 (environmental)** — LLM rate-limits (OpenAI + all 6 Groq keys) forced the deterministic fallback in the Docker phase on both runs; consider higher-tier keys for a clean LLM-path validation.

---

## 8. REGRESSION GOAL STATUS (the 11 previously-fixed issues)

| # | Goal | Run 2 verdict |
|---|---|---|
| 1 | Terraform artifact persistence | ✅ PASS (6 DB rows) |
| 2 | Terraform DB rehydration | ✅ PASS |
| 3 | Terraform validation execution | ✅ PASS (`ok=true`) |
| 4 | Terraform plan execution | ❌ **FAIL** — plan errors on ALB/TG name length (H-1) |
| 5 | Terraform name sanitization | ❌ **PARTIAL/REGRESSED** — starts-with-letter ✓, but no suffix headroom ⇒ ALB/TG > 32 (H-1) |
| 6 | Docker HEALTHCHECK sanitization | ✅ PASS — `HEALTHCHECK NONE` valid, no `\n` escapes (exercised this run) |
| 7 | Docker artifact persistence | ✅ PASS (4 DB rows) |
| 8 | Replay determinism | ✅ PASS — reproduces success and failure with no drift |
| 9 | Observability correctness | ⚠️ PARTIAL — completeness truthful; classification gaps (M-3) |
| 10 | Single workflow enforcement | ✅ PASS — idempotent re-POST returns same workflow |
| 11 | State consistency | ✅ PASS — 1 active wf, 1 task, 7 unique phases, trace consistent |

---

## 9. RELEASE VERDICT

# ❌ NOT RELEASE READY

**Justification.** With Docker, Qdrant, and MCP all up, two pipeline phases fail due to **genuine code/content defects, not environment**:

1. **H-1 (terraform plan / name sanitization)** is the decisive blocker: `terraform plan` fails deterministically because ALB and target-group names exceed AWS's 32-char limit. Because `project_name` comes from the task UUID, this affects the **majority** of projects — Run 1's pass was coincidental. This regresses the "Terraform plan execution" and "Terraform name sanitization" guarantees the freeze is meant to protect.

2. **H-2 (docker fallback quality)** means the resilience path can emit an unbuildable Dockerfile (JRE base + `mvn`), and the build now fails for real once a daemon is present.

The platform's **resilience and plumbing are solid** — DB-first persistence, rehydration, deterministic replay (incl. of failures), graceful non-raising phases, corrector auto-routing, single-workflow enforcement, and Docker daemon connectivity all behave correctly. But the **generated content** is not release-quality on this representative input.

**Required before re-freeze:**
1. Fix `sanitize_terraform_name` (or the templates) to reserve headroom for resource suffixes so ALB/TG names stay ≤ 32 (e.g., cap `project_name` at ~24 chars, or apply per-resource truncation/`name_prefix`). Add the ALB/TG-suffix case to `tests/test_output_hardening.py`.  **(H-1)**
2. Fix the Maven fallback Dockerfile (multi-stage build with a Maven/JDK builder stage; never run `mvn` on a JRE base) and make the fallback deterministic.  **(H-2)**
3. Reconcile the RAG collection name across `.env`, `rag_pipeline_service`, and the actual Qdrant collection.  **(M-1)**
4. Fix the RDS `db_engine`/`engine_version`/SG-port mismatch.  **(M-2)**
5. Propagate real failure classifications for terraform-plan and docker-build into `terraform_status` / `failure_classifications`.  **(M-3)**

---

### Appendix — Run 1 vs Run 2 (environment delta)

| Phase | Run 1 (Docker/Qdrant/MCP **down**) | Run 2 (all **up**) |
|---|---|---|
| Terraform plan | PASS (23 resources) — *lucky 27-char name* | **FAIL** — ALB/TG name >32 (31-char name) |
| Docker generation | fallback → correct multi-stage Dockerfile | fallback → **broken** single-stage (JRE+mvn) |
| Docker build | FAIL — daemon unreachable (environmental) | **FAIL — `mvn: not found`** (generation defect; daemon proven up) |
| RAG | n/a (Qdrant down) | **collection mismatch** — Qdrant up but unused |
| MCP | not loaded | loaded (`direct mode, mcp=true`) |
| Replay / Observability / State | PASS | PASS (replay also reproduces failures) |

*Report generated by automated QA execution against the live backend. No source files were modified. Evidence persisted in PostgreSQL (`devsecops_db`); the QA backend remains running on `127.0.0.1:8000`.*
