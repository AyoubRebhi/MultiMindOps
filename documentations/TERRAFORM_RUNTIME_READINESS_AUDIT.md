# Terraform Runtime Execution — Readiness Audit

**Audit date:** 2026-05-31
**Reviewers:** Principal Cloud Architect · Principal Security Engineer · Staff Platform Engineer · Terraform Runtime Reviewer
**Scope:** Deep verification of the post-Phase 1/2/3/4/5 platform against the bar for real `terraform init / plan / apply / destroy` against AWS.
**Method:** Code inspection (not assumption). Every finding cites a file:line or a verified absence.
**Verdict (preview):** **NO-GO.** Five P0 blockers and several P1 risks must be closed before any real infrastructure execution is wired up.

---

## 1. Authentication

### Finding A1 — JWT_SECRET default boots in production (P1)
**Evidence:** [backend/app/core/config.py#L115](../backend/app/core/config.py) — `JWT_SECRET: str = "dev-insecure-change-me"`. The validator at L193–199 logs a warning when `APP_ENV != "development"` but does NOT raise.
**Why it matters:** Anyone with a copy of the source can mint valid tokens for any user.
**Exploitation scenario:** A staging deploy where APP_ENV is misconfigured (left at default) → attacker reads the public repo → mints an OWNER access token for any user → calls `/api/projects/{any}/credentials` to exfiltrate AWS keys.
**Recommended fix:** Promote the validator from `warn` to `raise` when `APP_ENV != "development"` AND the default secret is in use. Same for empty secret.

### Finding A2 — `AUTH_ALLOW_DEV_FALLBACK` defaults to False but is only env-checked, not enforced at boot (P2)
**Evidence:** [backend/app/core/config.py#L126](../backend/app/core/config.py) defaults False, but there is no boot-time guard that raises if `AUTH_ALLOW_DEV_FALLBACK and APP_ENV != "development"`.
**Why it matters:** A single misconfigured env var converts every unauthenticated request into the dev seed user.
**Exploitation scenario:** Operator copies dev `.env` to prod, forgets to flip the flag → every unauthenticated request impersonates `dev@devsecops-ai.local`.
**Recommended fix:** Add `validate_provider_keys`-style assertion that hard-raises if both conditions are true.

### Finding A3 — WebSocket auth path is correct (positive) (—)
**Evidence:** [backend/app/api/routes/execution.py#L893–960](../backend/app/api/routes/execution.py) `_ws_authenticate` decodes the access JWT from `?token=`, calls `resolve_task_membership`, closes with 1008 BEFORE any log content is sent. Verified by inspection.

---

## 2. Authorization

### Finding Z1 — `require_role("ADMIN")` is a no-op stub (P1)
**Evidence:** [backend/app/core/authorization.py#L56–65](../backend/app/core/authorization.py) — the inner `_checker` returns `current_user` unconditionally regardless of whether ADMIN is requested. The comment says "Until a real ADMIN attribute lands, the dev user is treated as ADMIN" — but in fact every authenticated user is treated as ADMIN by this dependency.
**Why it matters:** Any route that depends on `require_role("ADMIN")` is effectively unprotected.
**Exploitation scenario:** When a future operator adds an admin-only endpoint (kill all jobs, force-revoke sessions, dump credentials) using this helper, every developer gets the kill switch.
**Recommended fix:** Add `users.is_admin` boolean (default false) + real enforcement, OR remove the alias until the column lands so misuse is impossible.

### Finding Z2 — Self-heal of OWNER membership runs inside an auth dependency (P2)
**Evidence:** [backend/app/core/authorization.py#L99–115](../backend/app/core/authorization.py) — `require_project_role` INSERTs a `project_members` row from inside the dependency on cache miss. The dependency runs on every project-scoped GET.
**Why it matters:** (a) audit trail is muddied — the OWNER row records `created_at` as the moment of first GET, not the moment the OWNER was actually granted access; (b) under concurrent first-access from the OWNER on two routes, the second INSERT relies on the unique constraint to fail gracefully — which works, but the dependency raises IntegrityError instead of retrying.
**Recommended fix:** Move the self-heal to project bootstrap (Project + OwnerMember inserted in the same transaction) and remove the runtime self-heal. Any project missing its OWNER row should be flagged by a startup integrity job, not silently patched on read.

### Finding Z3 — Legacy task-scoped routes now correctly gated (positive) (—)
**Evidence:** [backend/app/api/routes/workflow.py, execution.py, corrector.py, artifact_edit.py, tasks.py](../backend/app/api/routes/) all use `require_task_project_*`. Cross-project access returns 404 (not 403), preserving non-disclosure. Phase 1 invariant holds.

---

## 3. Multi-Tenancy Isolation

### Finding M1 — `Task.project_id` is NOT NULL + schema-guard enforced (positive) (—)
**Evidence:** [backend/app/models/task.py#L26–34](../backend/app/models/task.py); [backend/app/core/schema_guard.py#L346–353](../backend/app/core/schema_guard.py) — invariant declared AND boot fails if it ever regresses.

### Finding M2 — Per-project run lock enforced at DB layer (positive) (—)
**Evidence:** [backend/app/models/execution_job.py#L77–87](../backend/app/models/execution_job.py) — partial unique index `uq_execution_jobs_one_running_per_project` declared with both `postgresql_where` and `sqlite_where` so `create_all()` emits it on either backend. Phase 3 tests prove the IntegrityError path.

### Finding M3 — Worker claim is correct but NOT optimal under multi-worker load (P2)
**Evidence:** [backend/app/services/execution/job_service.py#L131–193](../backend/app/services/execution/job_service.py) — uses optimistic UPDATE + WHERE status='pending' to claim, falls back on IntegrityError. Correct, but doesn't use Postgres `FOR UPDATE SKIP LOCKED`.
**Why it matters:** Under N concurrent workers all racing the same candidate, only one wins; the rest waste a roundtrip per claim attempt. Not a correctness issue — a throughput issue at scale. Acceptable for the in-process worker today (max 1 process).
**Recommended fix:** When/if multi-process worker deployment lands, gate the claim behind `SELECT ... FOR UPDATE SKIP LOCKED` on Postgres.

### Finding M4 — Cross-project job addressability blocked at route layer (positive) (—)
**Evidence:** [backend/app/api/routes/jobs.py#L40–49](../backend/app/api/routes/jobs.py) — `_load_job_or_404` cross-checks `job.project_id == project_id` before any other action. 404 on mismatch.

---

## 4. Secrets Management

### Finding S1 — GitHub PAT can leak through `_sanitize_git_error` (P1)
**Evidence:** [backend/app/services/repository/github_service.py#L114, L126, L292–293](../backend/app/services/repository/github_service.py).
The clone URL is `https://x-access-token:<TOKEN>@github.com/...`. On clone failure:
```python
raise RuntimeError(f"Git clone failed: {self._sanitize_git_error(stderr)}")
```
And `_sanitize_git_error` does ONLY:
```python
return stderr.replace("\n", " ").replace("\r", " ").strip()
```
It strips newlines. It does NOT redact the token. If `git` echoes the URL into stderr (common on auth failures, redirect loops, malformed remotes), the token enters the RuntimeError message → propagates through `HTTPException(detail=str(exc))` to the API response.
**Why it matters:** The credential the operator just uploaded comes back out in plaintext, in a 5xx response body, to whatever client made the request.
**Exploitation scenario:** Attacker submits a workflow with a malformed private repo URL → the clone fails → the error response contains the operator's GitHub PAT.
**Recommended fix:** `_sanitize_git_error` must apply `backend.app.core.log_redaction.redact()` to stderr before returning. Also redact the RuntimeError message in the upstream HTTPException handler. Defence in depth — the log filter would catch the log line but does NOT touch HTTP response bodies.

### Finding S2 — AWS credential storage / injection is NOT implemented (P0)
**Evidence:** Grep for `aws_access_key_id|aws_secret_access_key|AWS_ACCESS_KEY|aws_iam` across `backend/app` returns ONLY template references in `terraform_generation/templates/**/*.tf.j2`. `KNOWN_PROVIDERS` in [credentials_service.py#L36](../backend/app/services/core/credentials_service.py) lists `"aws_iam"` but no service consumes it. No `aws_secret_access_key` is read from the credentials store anywhere.
**Why it matters:** Even if `TerraformExecutor` were built tomorrow, it has no way to receive AWS credentials. The encrypted store is wired for `github_pat` only.
**Recommended fix:** (1) Decide credential shape: short-lived STS via assume-role (preferred) vs. long-lived IAM keys. (2) Implement `aws_iam` provider in `CredentialsService` with a serialised JSON payload (access_key_id, secret_access_key, session_token, region, role_arn). (3) Add an AWS-credential hydrate helper that injects them into subprocess env (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`) only at terraform invocation time. (4) Strict log redaction patterns for AWS keys are already in `log_redaction._build_patterns` — verify they match the real key format the runtime will emit.

### Finding S3 — Encrypted credentials at rest (positive) (—)
**Evidence:** [backend/app/core/encryption.py](../backend/app/core/encryption.py) — Fernet (AES-128-CBC + HMAC-SHA256), key from `APP_SECRET_KEY` with multi-key rotation. [backend/app/services/core/task_service.py#L11–60](../backend/app/services/core/task_service.py) `_sanitize_for_json` scrubs a deny-list of secret-shaped keys from `workflow_state` AND `execution_jobs.execution_context`, case-insensitive, any depth.

### Finding S4 — `APP_SECRET_KEY` unset is warn-only at boot (P2)
**Evidence:** [backend/app/core/config.py#L202–213](../backend/app/core/config.py).
**Why it matters:** A production deployment without `APP_SECRET_KEY` silently disables credential storage; writes 503 at runtime instead of failing fast at boot.
**Recommended fix:** Hard-raise when `APP_ENV != "development"` AND `APP_SECRET_KEY` is unset.

### Finding S5 — `github_token` re-appears in orchestrator in-memory state (informational) (—)
**Evidence:** [backend/app/agents/orchestrator_agent.py#L1210](../backend/app/agents/orchestrator_agent.py) — `_base_state` puts `github_token` into the in-memory orchestrator state. This is fine: every persist path (`TaskService.save_workflow_state`, `save_plan_awaiting_validation`) runs `_sanitize_for_json` which strips it. The two write call sites grepped + verified.

---

## 5. Release Candidate Model

### Finding R1 — Release candidate snapshots are immutable + drift-detecting (positive) (—)
**Evidence:** [backend/app/models/release.py#L120–167](../backend/app/models/release.py) + [backend/app/services/core/release_service.py#L148–227](../backend/app/services/core/release_service.py). Phase 2 tests pin the drift / staleness / deletion / missing-type cases.

### Finding R2 — NO execution code path consumes a release candidate (P0)
**Evidence:** Grep for `ReleaseService\.|ReleaseCandidate|require_executable_candidate` across `backend/app` shows ZERO callers outside of `release_service.py`, `releases.py` (the API), `execution_policy.py` (the unused policy layer), and tests. The actual Docker build path [execution.py#L582–818](../backend/app/api/routes/execution.py) checks the `current_phase` string and pre-build validation only — never a release candidate.
**Why it matters:** The whole release-approval system is currently **decorative**. A `CLOUD_ARCHITECT` can approve a candidate — but execution does not consult it. If TerraformExecutor lands without adding the gate, the approval system remains decorative for Terraform too.
**Exploitation scenario:** Developer edits Dockerfile bypassing the (in-future) Terraform release-approval flow. There is no platform code that compares the executor's inputs to an approved candidate; the only thing stopping execution is the absence of a `terraform apply` button.
**Recommended fix:** Before TerraformExecutor ships, every executor entry point MUST call `require_executable_candidate(db, candidate)` and refuse on `executable=False`. Wire it into the worker handler's pre-flight, not into the route, so the gate cannot be bypassed by enqueueing a job directly.

### Finding R3 — `ReleaseService.mark_executed` is never called (P1)
**Evidence:** Grep — only definition. No production path transitions a candidate to `executed`. Therefore `_mark_others_superseded` never fires. Candidates accumulate in `approved` state indefinitely.
**Why it matters:** The lifecycle the model promises (draft → approved → executed → superseded) is half-wired. The UI cannot reliably show "this candidate ran" vs. "this candidate was approved but never used".
**Recommended fix:** TerraformExecutor MUST call `mark_executed` in its success/finally path. Also surface a daily reaper that supersedes candidates older than N days that were never executed.

---

## 6. Approval Model

### Finding AP1 — Hash-binding + edit-invalidation correct (positive) (—)
**Evidence:** [backend/app/services/core/artifact_persistence_service.py#L207–240](../backend/app/services/core/artifact_persistence_service.py) clears `approval_state`, `approved_by`, `approved_at`, `approved_content_hash` on any content change. Phase 2 tests cover the matrix.

### Finding AP2 — Approval bound to artifact, not to a release candidate (P1)
**Evidence:** [backend/app/services/core/artifact_approval_service.py](../backend/app/services/core/artifact_approval_service.py) — `record()` approves AN artifact. There is no separate "release approval" decision recorded; release-candidate `approve()` flips `status` but does not write into `artifact_approvals`.
**Why it matters:** Audit trail is split: "who approved this release" lives on `ReleaseCandidate.candidate_metadata` (not currently populated by the route either) while artifact-level approval is in `artifact_approvals`. Post-mortem of "who said yes to this apply" requires correlating two tables that aren't linked by FK.
**Recommended fix:** Add `release_approvals` table OR add an `approved_by` + `approval_decision_id` to ReleaseCandidate. Either way, the formal release approval (the act of clicking "Approve release") must be its own auditable row.

### Finding AP3 — `request_changes` and `reject` do not invalidate sibling artifacts in the same candidate (P2)
**Evidence:** [backend/app/services/core/artifact_approval_service.py#L66–82](../backend/app/services/core/artifact_approval_service.py) operates per-artifact. If a reviewer rejects ONE artifact in a 5-artifact candidate, the others stay in their prior state.
**Why it matters:** Mostly desirable, but if a release "fails review" we should be able to tell at a glance which candidate is dead.
**Recommended fix:** When `reject` lands on an artifact in an active candidate, also flip the candidate to `rejected` automatically — and emit an event.

---

## 7. Artifact Lifecycle

### Finding L1 — Content hashing deterministic + version trail intact (positive) (—)
**Evidence:** [backend/app/services/core/artifact_persistence_service.py#L26–35](../backend/app/services/core/artifact_persistence_service.py); [artifact.py#L83–96](../backend/app/models/artifact.py) `ArtifactVersion.content_hash` stamped at insert.

### Finding L2 — `Task.workflow_state` artifact store NOT bridged to `Artifact` rows (P1)
**Evidence:** [backend/app/api/routes/artifact_edit.py#L82–110](../backend/app/api/routes/artifact_edit.py) — PATCH writes to `Task.workflow_state["artifacts"][key]["current_content"]` via `ArtifactService.save_many_artifacts`. The project-scoped `Artifact` row is updated only when `ArtifactPersistenceService.persist_state_artifacts` runs (after a phase). A user PATCH does NOT bump the `Artifact.content_hash` / invalidate approval until the next phase persists.
**Why it matters:** A user edits Dockerfile via PATCH → the artifact_edit route returns success → but `Artifact.approval_state` still says `approved` because the live row was not touched. If TerraformExecutor (or anything else) reads the `Artifact` row, it gets the OLD content while executing the NEW content from `workflow_state`.
**Exploitation scenario:** Approver approves Terraform main.tf → developer PATCHes the artifact via the artifact_edit endpoint → executor reads from workflow_state (sees new content) but the gate reads from the `Artifact` row (sees approved old content) → drift undetected, gate passes, modified terraform applies.
**Recommended fix:** `ArtifactService.save_many_artifacts` MUST also upsert the `Artifact` row in the same transaction (re-hash + invalidate approval). OR: collapse the dual model entirely so `Artifact` is the single source of truth and `workflow_state["artifacts"]` is removed.

### Finding L3 — No content-hash backfill for legacy approval rows (P2)
**Evidence:** [backend/migrations/phase2_governance_enforcement.sql#L37–57](../backend/migrations/phase2_governance_enforcement.sql) — backfills `content_hash` but leaves `artifact_approvals.approved_content_hash` NULL on historical rows.
**Why it matters:** The enforcement gate refuses an artifact whose `approved_content_hash != snapshot_hash`. For legacy-approved artifacts, that comparison is `NULL != some_hash` → refused, treating them as unverified. This is the safe default but means every legacy approval must be re-approved before that artifact can ride in any release. The migration calls this out but operators may miss it.
**Recommended fix:** Add an admin command + a release-note flag that flips legacy approvals back to `pending_review` explicitly so the UI shows them in the re-review queue.

---

## 8. Event Sourcing Model

### Finding E1 — `WorkflowEventService` is never called outside its own tests (P0)
**Evidence:** Grep for `WorkflowEventService|WorkflowPhaseEvent` across `backend/app` outside the service module returns ONLY:
- `models/__init__.py` (import)
- `models/workflow_event.py` (definition)
- `services/core/workflow_event_service.py` (definition)

No call site in `workflow_orchestration_service.py`, `execution.py`, `release_service.py`, `execution_worker.py`, `releases.py`, or any handler. The event log is **empty** for every workflow in production code paths.
**Why it matters:** The whole "derived_current_phase" / immutable audit story is decorative until something emits events. The audit's "Workflow.current_phase is unforgeable string" risk is unchanged.
**Exploitation scenario:** Operator queries the event log to find out who approved the apply → returns empty list. The only audit signal is `Workflow.current_phase`, a mutable column.
**Recommended fix:** Before TerraformExecutor ships:
- WorkflowOrchestrationService.start_workflow → emit `(ARCHITECTURE_DECISION, started)`
- WorkflowOrchestrationService.select_plan → emit `(PLAN_SELECTED, succeeded)`
- WorkflowOrchestrationService.run_phase → emit `(<PHASE>, started)` + `(<PHASE>, succeeded|failed)`
- releases.py approve/reject → emit `(RELEASE_APPROVED|RELEASE_REJECTED, …)`
- execution_worker supervisor → emit `(<phase>, started)` + terminal status
This is mechanical work but it MUST land before TerraformExecutor or the apply has no audit trail.

### Finding E2 — `Workflow.current_phase` and the event log will diverge silently (P2)
**Evidence:** [backend/app/models/workflow.py#L29](../backend/app/models/workflow.py) `current_phase` is a mutable String column updated by orchestration service. Once events start being emitted (Finding E1), reconciliation must happen.
**Why it matters:** Two truths drift inevitably.
**Recommended fix:** Treat the event log as authoritative; downgrade `Workflow.current_phase` to a denormalised cache populated from the latest event (or remove it entirely). Add a startup integrity sweep that flags workflows where `current_phase != derived_current_phase`.

---

## 9. Durable Job Execution

### Finding J1 — Job substrate works end-to-end (positive) (—)
**Evidence:** [backend/app/services/execution/job_service.py](../backend/app/services/execution/job_service.py) + [backend/app/workers/execution_worker.py](../backend/app/workers/execution_worker.py). Phase 3 tests prove: claim atomicity, per-project lock, heartbeat, reap+requeue, idempotency dedupe, cancel.

### Finding J2 — Shutdown grace (30 s) << Docker build timeout (40 min) (P0 for terraform; P1 for current Docker)
**Evidence:** [execution_worker.py#L59](../backend/app/workers/execution_worker.py) `shutdown_grace_seconds: float = 30.0`; [docker_executor.py#L39](../backend/app/services/execution/docker_executor.py) `BUILD_TIMEOUT_SECONDS = 2400`. The shutdown logs "grace expired … leaving them running; the next worker will reap if the heartbeat goes stale." But the heartbeat is alive WHILE the build runs in the same process, until the process exits.
**Why it matters:** A `kubectl rollout` / Docker SIGTERM kills the API process. The in-process worker's shutdown hands the asyncio gather a 30 s budget, then returns. The subprocess (docker build / future terraform apply) inherits the parent's death — on Linux, child processes are NOT automatically killed by parent shutdown, but the subprocess WILL die when the asyncio gather is cancelled and the surrounding `_run_cmd` context manager unwinds the subprocess handle. The job row stays `running` with a fresh heartbeat (last bump was within the heartbeat interval). The reaper picks it up after `EXECUTION_JOB_HEARTBEAT_TIMEOUT_SECONDS = 60` and re-queues it.
**Re-queue means re-RUN.** For Docker that's harmless: the build is idempotent. **For `terraform apply` that means RE-APPLY — creating duplicate AWS resources** if the first apply got partway through before the SIGTERM, because terraform's state-locking does survive the crash but the in-progress changes do not.
**Exploitation scenario:** Routine API redeploy during a long apply → apply orphaned mid-way → reaper re-queues → second apply runs `terraform apply` against a state file that has a stuck lock (or has been released by another process) → either fails on the lock (acceptable) or proceeds and double-creates resources (disastrous).
**Recommended fix:** Three layers:
1. Raise `shutdown_grace_seconds` to at least `BUILD_TIMEOUT_SECONDS + heartbeat_timeout` (40 min + 1 min) OR have the lifespan REFUSE to shut down until all in-flight jobs reach terminal status (with an override for "force-kill, accept the orphan risk").
2. The reaper for `terraform_apply` / `terraform_destroy` jobs MUST NOT auto-re-queue — it must mark them `failed` with `error_message="possibly-incomplete apply, manual review required"` and refuse to re-run without explicit operator decision (a "force-retry" endpoint).
3. The TerraformExecutor must obtain its state lock under a job-id key + check on retry whether a previous job for this candidate left a lock; if so, fail loudly until the operator cleared it.

### Finding J3 — In-process worker shares the API event loop (P2)
**Evidence:** [backend/app/core/app_factory.py#L140–149](../backend/app/core/app_factory.py) — `start_in_process_worker()` from the lifespan. The worker's polling, heartbeat, and handler tasks all run on the same asyncio loop as request handlers.
**Why it matters:** A 40 minute Docker build holds two of the worker's concurrency slots. The HTTP server keeps responding (separate accept loop in uvicorn workers) but any in-request awaiting on the loop competes with the build's I/O. Worse, a single uvicorn process is currently both API and worker; running multiple uvicorn workers means N in-process workers — N times the concurrency cap, all reading/claiming from the same DB.
**Recommended fix:** Document that production runs ONE API process with the in-process worker, OR run the worker as a separate `python -m backend.app.workers.execution_worker` process and set `EXECUTION_WORKER_ENABLED=false` on the API. The standalone path is implemented; just not the default. Decide before terraform execution.

### Finding J4 — No subprocess hard-kill on cancel (P1 for Docker, P0 for Terraform)
**Evidence:** [backend/app/workers/handlers.py#L60–70](../backend/app/workers/handlers.py) and [docker_executor.py#L859–870](../backend/app/services/execution/docker_executor.py) — the handler's cancellation cancels the asyncio task. The docker subprocess is invoked via `asyncio.create_subprocess_exec`; cancelling the awaiting coroutine does NOT send SIGKILL to the child. The process keeps running until it finishes.
**Why it matters:** "User clicked cancel" returns 200 immediately, but the terraform apply continues quietly, finishes, and the state file is updated against the operator's stated intent. The audit's "Destroy mid-apply" risk is wide open.
**Recommended fix:** `DockerExecutor` and the (future) `TerraformExecutor` must implement `_run_cmd` with explicit `proc.terminate()` then `proc.kill()` in a `finally` triggered by `asyncio.CancelledError`. Document the kill-grace contract per executor (terraform should get longer than docker to flush state).

### Finding J5 — `idempotency_key` collision window for Docker retry (P3)
**Evidence:** [execution.py#L786](../backend/app/api/routes/execution.py) — `idempotency_key=f"docker_build:{task_id}:{build_number}"`. `build_number` is incremented BEFORE enqueue in the same handler. A double-click → both requests compute the same build_number from the same state snapshot → idempotency key matches → second enqueue returns the same job. Good.
**However:** the phase-transition check (`state["current_phase"] = "docker_build_running"` then save) is NOT atomic with the enqueue. Two simultaneous requests both read `state.current_phase == "docker_completed"`, both compute `build_number = N`, both attempt to save. Whichever commits first wins; the second sees `docker_build_running` next time. But the WINDOW between read and save allows a race where two jobs CAN be enqueued with different build numbers — and both pass the idempotency check (different keys).
**Why it matters:** Today, the per-project run-lock catches it (only one runs). For terraform_apply the same race could squeeze through if build_number-like discriminator is wrong.
**Recommended fix:** Use an idempotency key derived from `(release_candidate_id, candidate.version_at_request_time)` for terraform jobs. The candidate is the unit of work; the candidate id is stable; double-clicks dedupe regardless of build counters.

---

## 10. Execution Policies

### Finding P1 — ExecutionPolicy is built but never called in production code (P0)
**Evidence:** Grep for `terraform_apply_policy|approval_gate|severity_gate|ExecutionContext` across `backend/app` returns ZERO callers outside `execution_policy.py` itself and its tests. The matches in `backend/app/agents/orchestrator_agent.py` / `cicd_*` are an unrelated "execution_policy" concept (CI/CD artifact contract) — different layer entirely.
**Why it matters:** A whole gate library exists and PASSES tests, but no executor or worker invokes it. Building TerraformExecutor on top of this without wiring the gates is the EXACT failure mode the prior audit flagged: gates exist, executor forgets to call them.
**Recommended fix:** The TerraformExecutor handler MUST call `evaluate(ctx, terraform_apply_policy())` as its FIRST step after job claim. Bake the call into the handler signature with a decorator or base class so a future executor cannot ship without it. Equivalent for `terraform_destroy_policy()` (same gates plus a "typed-confirmation-string" gate).

### Finding P2 — No "cost ceiling" gate exists (P2)
**Evidence:** [execution_policy.py](../backend/app/services/execution/execution_policy.py) ships approval, severity, stale_plan, environment_isolation gates. The prior audit asked for cost-control governance. The cost estimation agent runs at plan time, but the result does not feed a runtime gate.
**Why it matters:** A plan that estimates $25k/month should not be applicable by a developer without a separate approval. Today nothing enforces this.
**Recommended fix:** Add `make_cost_ceiling_gate(monthly_usd=N)` reading from `release_candidate.candidate_metadata["estimated_monthly_cost"]`. Plumb the cost into candidate metadata at creation time (the cost agent already produces it).

### Finding P3 — Severity gate fails-closed on missing scanner result (positive) (—)
**Evidence:** [execution_policy.py#L150–162](../backend/app/services/execution/execution_policy.py). A `None` severity returns deny with "validator did not run" — exactly the safe default the prior audit specified.

### Finding P4 — Environment isolation gate requires explicit setup (P1)
**Evidence:** [execution_policy.py#L192–214](../backend/app/services/execution/execution_policy.py). The gate denies when either `executor_environment` or `candidate_environment` is missing. Good. But there is NO platform code today that populates `release_candidate.candidate_metadata["environment"]` or attaches an environment tag to the executor.
**Why it matters:** Operators MUST configure environment tagging end-to-end before this gate is meaningful; otherwise it just refuses every execution unconditionally, which then invites a workaround.
**Recommended fix:** Make environment a first-class field on `ReleaseCandidate` (`environment: str` column, NOT NULL on the migration). The candidate-create endpoint requires it. The executor reads its own `EXECUTOR_ENVIRONMENT` env var (settings). The gate becomes meaningful without operator JSON-blob discipline.

---

## 11. Workflow Consistency

### Finding W1 — Two parallel artifact stores (P1 — see L2)
Already covered in §7 Finding L2. The dual `workflow_state["artifacts"]` ↔ `Artifact` table model is the central consistency hazard. Edits via the user-edit route do not invalidate approval until the next phase persists. Closing this is a precondition for governance to be honest.

### Finding W2 — `Workflow.current_phase` updated outside transactions (P2)
**Evidence:** [backend/app/services/core/workflow_orchestration_service.py#L116–129, #L226–229](../backend/app/services/core/workflow_orchestration_service.py) — `workflow.current_phase = …` is set + committed alongside other writes. Mostly safe via SQLAlchemy unit-of-work, but the execution.py path writes `state["current_phase"]` to `Task.workflow_state` JSONB (a separate row, separate transaction).
**Why it matters:** Workflow.current_phase and Task.workflow_state.current_phase can disagree. Today they're loosely consistent because writes happen in close succession; under load + retry they drift.
**Recommended fix:** Treat the event log (Finding E1) as the authoritative truth and demote BOTH `current_phase` columns to caches with a startup reconciliation.

---

## 12. Database Consistency

### Finding D1 — `User.is_active` / `email_verified` / `account_status` are still String "true"/"false" (P3)
**Evidence:** [backend/app/models/user.py#L24, L34, L36](../backend/app/models/user.py).
**Why it matters:** SQL queries `WHERE is_active = TRUE` will silently miss rows. The model worksaround via `is_active_bool` but storage carries the legacy schema.
**Recommended fix:** Migration to convert columns to BOOLEAN. Not blocking for Terraform.

### Finding D2 — `ProjectMember.role` CHECK constraint added (positive) (—)
**Evidence:** [backend/migrations/phase1_authz_unification.sql#L78–88](../backend/migrations/phase1_authz_unification.sql). A direct UPDATE to an unknown role is now rejected at the DB.

### Finding D3 — No retention policy on `execution_jobs`, `workflow_phase_events`, `user_sessions` (P2)
**Evidence:** Grep for "DELETE FROM execution_jobs" / cron / cleanup returns nothing.
**Why it matters:** Tables grow unboundedly. The `user_sessions.expires_at` index was added in Phase 1 specifically to enable cheap cleanup — but no job runs that sweep.
**Recommended fix:** A periodic reaper (could be a recurring job in the job system itself) that deletes terminal-and-old jobs/sessions/events.

### Finding D4 — `tasks.workflow_state` JSONB row size is unbounded (P2)
**Evidence:** [execution.py#L432–467](../backend/app/api/routes/execution.py) — Docker build logs accumulate in `state["execution"]["docker"]["logs"]` per retry. Not capped.
**Why it matters:** A long terraform apply with `TF_LOG=DEBUG` would explode the row size to MBs and hit Postgres TOAST inefficiency.
**Recommended fix:** Move logs out of `workflow_state` into a dedicated `execution_logs` append-only table keyed by `(job_id, line_no, timestamp, line)`. Phase 3's `logs_reference` field on `ExecutionJob` already anticipates this — implement the dedicated store before Terraform.

### Finding D5 — Schema-guard NOT NULL invariant pattern works (positive) (—)
**Evidence:** [backend/app/core/schema_guard.py#L325–355, #L500–525](../backend/app/core/schema_guard.py) — refuses boot if `tasks.project_id` is nullable or has NULL rows. Phase 1 invariant proven by tests.

---

## 13. Concurrency Risks

### Finding C1 — Per-project run lock at DB level (positive) (—)
Already covered in §3.

### Finding C2 — Release candidate `evaluate()` is not atomic with artifact mutation (P1)
**Evidence:** [backend/app/services/core/release_service.py#L148–227](../backend/app/services/core/release_service.py) — re-reads live artifacts via `db.query(Artifact).filter(Artifact.id.in_(…)).all()` and compares hashes. If an artifact edit lands BETWEEN this read and the executor's invocation, the gate's verdict is stale.
**Why it matters:** Operator approves candidate → user edits a Dockerfile in the same project → executor runs `evaluate` (passes — they edited Dockerfile, not the terraform artifact) → but a different reader at the same moment sees inconsistent state.
For Terraform specifically: the gate must run not just at approval, but ALSO at the start of the apply with the artifacts FETCHED FROM THE SNAPSHOT, not refetched from live rows. Right now `evaluate` refetches from live, which is correct for drift detection but means a same-moment edit can race.
**Recommended fix:** Wrap the gate-and-then-apply sequence in a Postgres advisory lock keyed by `(project_id, target_phase)`. Inside the lock: re-evaluate THEN execute THEN release. Combined with the partial-unique-index per-project run-lock, this gives a strict serial ordering for governance-bound operations on a project.

### Finding C3 — Heartbeat task is best-effort, not authoritative (P2)
**Evidence:** [backend/app/workers/execution_worker.py#L189–212](../backend/app/workers/execution_worker.py) — `_heartbeat_until_done` sleeps `heartbeat_interval` (default 10 s) and only THEN refreshes. If the handler is doing CPU-heavy work that monopolises the asyncio loop, the heartbeat won't fire and the reaper will declare the job orphaned.
**Why it matters:** Python `await asyncio.sleep` cooperates with the loop. Subprocess wait DOES yield. But any sync-blocking Python work in the handler will starve the heartbeat → false reap → spurious retry.
**Recommended fix:** Run handlers in a thread executor if they can block, OR have the heartbeat run in a separate thread, OR explicitly forbid sync-blocking work in handlers and verify with a debug profiler.

---

## 14. Cancellation Behavior

### Finding CN1 — Pending cancel works correctly (positive) (—)
**Evidence:** [job_service.py#L228–245](../backend/app/services/execution/job_service.py) `request_cancel` for pending jobs transitions immediately. Phase 3 tests pin it.

### Finding CN2 — Running cancel does not kill subprocess (P0 — see J4)
Already covered.

### Finding CN3 — Cancellation race during status finalisation (P2)
**Evidence:** [execution_worker.py#L155–187](../backend/app/workers/execution_worker.py). The supervisor's finalisation reads `is_cancel_requested` AFTER the handler returns. A cancel that arrives BETWEEN handler success and supervisor finalisation will flip a `succeeded`-bound job to `cancelled`.
**Why it matters:** Subtle but real for audit: an operator clicks cancel at the same instant the job naturally completes; the audit log shows `cancelled` for what actually succeeded. For a Terraform apply, this means the audit says "user cancelled the apply" but the resources are actually live in AWS.
**Recommended fix:** Resolve the race in favour of the actual outcome: if `result is not None` and no exception was raised, the job SUCCEEDED, and a `cancel_requested` arriving after the handler returned should be ignored (or recorded as "cancel-requested-after-success" in metadata, not as the terminal status).

---

## 15. Audit Trail Integrity

### Finding AT1 — Approval audit trail intact at artifact level (positive) (—)
**Evidence:** `artifact_approvals` is append-only by service convention; `approved_content_hash` + `approved_version` are captured on every decision.

### Finding AT2 — Release-level audit trail incomplete (P1 — see AP2)
Already covered in §6.

### Finding AT3 — Execution audit trail = log lines in JSONB + execution_jobs.result_summary (P1)
**Evidence:** No structured audit of "X user triggered apply Y for project Z at time T against candidate C with plan hash H". The `ExecutionJob` row has `phase`, `started_at`, `worker_id`, `result_summary` (free-form JSONB).
**Why it matters:** A post-incident review of "who applied what, when, against which AWS account, with what plan" is going to be archaeology. For SOC2/audit-ready execution this is insufficient.
**Recommended fix:** Combine Finding E1 (emit workflow events) with a structured `ExecutionAuditEntry` table covering: actor, project, candidate, plan_hash, target_aws_account, start, end, outcome, error_class. Distinct from logs (which are TF stdout).

### Finding AT4 — Workflow event log empty (P0 — see E1)
Already covered.

---

## 16. Terraform Readiness

### Finding T1 — `TerraformExecutor` does not exist (P0)
**Evidence:** Grep for `class TerraformExecutor|terraform_executor|terraform init|terraform apply|terraform plan|terraform destroy` in `backend/app` returns: the validator (init -backend=false, no apply), template references, docstrings. **No executor.**
**Why it matters:** Literally cannot execute Terraform. This is the gating fact.
**Recommended fix:** Build it — but only AFTER closing the other P0s, so it can be built on a substrate it actually uses.

### Finding T2 — Deterministic `backend.tf` injector exists (positive) (—)
**Evidence:** [backend/app/services/terraform_generation/backend_injector.py](../backend/app/services/terraform_generation/backend_injector.py) — env-driven, refuses to fall back to LLM, per-task state key, validates bucket/region/table format.

### Finding T3 — No boot-time check that TF_STATE_* env vars are reachable (P2)
**Evidence:** [backend_injector.py#L70–105](../backend/app/services/terraform_generation/backend_injector.py) — raises at first use (per-task render). No validation that `aws s3 head-bucket TF_STATE_BUCKET` succeeds before the platform serves requests.
**Why it matters:** A misconfigured TF_STATE_BUCKET fails at the moment of the first apply, after the operator has invested time in plan+approval.
**Recommended fix:** Add a `validate_terraform_state_backend()` to the lifespan when `EXECUTION_WORKER_ENABLED` and a known "terraform-execution-enabled" flag is set.

### Finding T4 — State-key is per-task, not per-environment (P1)
**Evidence:** [backend_injector.py#L65–67](../backend/app/services/terraform_generation/backend_injector.py) — `tasks/{task_id}/terraform.tfstate`.
**Why it matters:** No env separation. The same workflow promoted dev→staging→prod overwrites its own state.
**Recommended fix:** State key must encode environment: `environments/{env}/projects/{project_id}/tasks/{task_id}/terraform.tfstate`. Pair with environment isolation gate (Finding P4).

### Finding T5 — No plan-hash linkage between plan output and approval (P0)
**Evidence:** `stale_plan_gate` exists ([execution_policy.py#L165](../backend/app/services/execution/execution_policy.py)) but there is no code that PRODUCES a plan hash or STORES it on a release candidate. The gate would deny every apply because `approved_plan_hash` is always None.
**Why it matters:** Without a stored plan hash, the gate that protects against "apply differs from plan" cannot enforce. This is a critical Terraform safety primitive.
**Recommended fix:** TerraformExecutor flow MUST be: (1) run `terraform plan` as a SEPARATE job, store `sha256(plan-output)` in `release_candidate.candidate_metadata["approved_plan_hash"]` at approval time; (2) `terraform_apply` re-plans, compares hash, calls `stale_plan_gate`, applies only if match.

### Finding T6 — `terraform destroy` has no typed-confirmation gate (P0)
**Evidence:** No "operator must type project name" or typed-confirmation gate exists. The audit's original fix list called for it.
**Why it matters:** Destroy is irreversible. A misclick or a hijacked session can erase AWS resources.
**Recommended fix:** Add `typed_confirmation_gate(expected: str)`. The destroy endpoint requires the operator to POST `{"confirm": "<project name typed verbatim>"}`. Wire the gate into `terraform_destroy_policy`.

---

## 17. AWS Readiness

### Finding AW1 — No AWS credential provider in CredentialsService (P0 — see S2)
Already covered.

### Finding AW2 — No IAM role boundaries / assume-role pattern (P1)
**Evidence:** No code that calls STS or AssumeRole. The expected production pattern is: platform holds a "deployer" role per environment; each project's `aws_iam` credential is the OUTPUT of an AssumeRole call, scoped to that project's resources by a per-project ExternalId.
**Why it matters:** If long-lived IAM keys are stored per project, leak blast radius = the project's entire AWS scope forever. Short-lived STS credentials limit blast radius to the credential's TTL.
**Recommended fix:** Make `aws_iam` provider a role-arn + external-id; the credential consumer calls STS at apply time and gets a 1-hour token. Encrypted store holds the role-arn (not a secret) — the only real secret is the platform's deployer IAM credentials, in env vars on the worker host.

### Finding AW3 — No AWS account/region pin per project (P1)
**Evidence:** `Project.project_metadata` is free-form JSONB. No structured `aws_account_id` / `aws_region` columns.
**Why it matters:** No platform-level guard against "executor running with prod credentials, against a state file labeled dev". The environment_isolation_gate (Finding P4) catches the env-tag mismatch; this is the AWS-side equivalent.
**Recommended fix:** Add `Project.aws_account_id` (validated format) + `Project.aws_default_region`; AWS credential payload must match; gate refuses execution on mismatch.

### Finding AW4 — No cost estimation feeds runtime gate (P2 — see P2)
Already covered.

---

## 18. Cost Governance Readiness

### Finding CG1 — Cost estimation exists at plan time, not at apply time (P1)
**Evidence:** [backend/app/agents/cost_estimation_agent.py](../backend/app/agents/) (from earlier audit context). The output is not consumed by any runtime gate.
**Why it matters:** A developer can approve a $25k/month plan with no platform check.
**Recommended fix:** See Finding P2. Pipe cost estimate into `candidate_metadata` at create-candidate time; `cost_ceiling_gate` refuses apply if above the operator-configured threshold (env: `MAX_MONTHLY_USD_NO_OWNER_APPROVAL=500`, etc.).

### Finding CG2 — No spend-rate / runaway detection (P2)
**Evidence:** Nothing in the codebase queries AWS Cost Explorer or budgets.
**Why it matters:** Once apply happens, ongoing cost is invisible to the platform. A misconfigured autoscale = runaway bill.
**Recommended fix:** Out of scope for the executor itself, but the operational layer needs `aws ce get-cost-and-usage` polling per project. Future phase.

---

## 19. Operational Readiness

### Finding O1 — In-process worker single-process limitation (P2 — see J3)

### Finding O2 — No admin "kill switch" (P1)
**Evidence:** No endpoint that stops ALL running jobs. Cancel is per-job.
**Why it matters:** Production incident: misbehaving worker spawning bad applies. Operator wants to pause everything until human investigation. No mechanism today.
**Recommended fix:** `POST /api/admin/pause` (real ADMIN gate — see Z1) that sets a global flag the worker checks before each claim; combined with a "cancel all running" sweep.

### Finding O3 — No structured deployment runbook for the migrations (P2)
**Evidence:** Migration files have operator notes but no overall sequence. The order is: phase1_authz_unification → auth_foundation → collaboration_layer → project_centric_phase1 → phase4_encrypted_credentials → phase3_execution_jobs → phase2_governance_enforcement → phase5_workflow_events. With prerequisites between them.
**Why it matters:** A wrong-order migration leaves the DB partially upgraded; the schema guard catches the broken state and refuses to boot, but the recovery story is unclear.
**Recommended fix:** A `backend/migrations/RUNBOOK.md` listing the exact apply order and prerequisites; a `make migrate` target that applies them in sequence.

### Finding O4 — No request-id propagation (P2)
**Evidence:** Log lines carry their own context but no shared correlation id.
**Why it matters:** Cross-service trace of "what happened to my apply" is hand-pieced from timestamps.
**Recommended fix:** Middleware that stamps `X-Request-ID` (echoed back) and pushes it onto a contextvar that the logger picks up. Tracing 101.

### Finding O5 — Worker shutdown grace mismatch (P0 — see J2)
Already covered.

---

## 20. Production Readiness

### Finding PR1 — Test suite at 164 passing is meaningful BUT (positive with caveat)
**Evidence:** Phase 1+2+3+4+5 tests all green. No integration tests against real Postgres / real Docker / real terraform.
**Why it matters:** All tests run on in-memory SQLite via JSONB→JSON variant. Postgres-only behaviour (`FOR UPDATE SKIP LOCKED`, JSONB operators, advisory locks) is unexercised.
**Recommended fix:** Add a CI job that boots a real Postgres + runs the Phase 3 + Phase 2 tests against it. Confirms the partial unique index emits correctly under real DDL, claim_next_job under concurrent workers, etc.

### Finding PR2 — Frontend stores access + refresh tokens in localStorage (P1 — unchanged from original audit)
**Evidence:** [frontend-React/src/lib/tokenStorage.ts](../frontend-React/src/lib/tokenStorage.ts).
**Why it matters:** XSS = wholesale credential theft. Refresh token has 14-day lifetime.
**Recommended fix:** httpOnly + SameSite=strict cookie for the refresh token (custom path `/api/auth/refresh`); access token in memory.

### Finding PR3 — CORS allow_methods=["*"], allow_headers=["*"] with credentials (P2 — unchanged)
**Evidence:** [backend/app/core/app_factory.py#L155–161](../backend/app/core/app_factory.py).
**Why it matters:** Acceptable in dev (allowlist is localhost only). In prod with credentials enabled, every method+header is allowed — a CSRF surface widener.
**Recommended fix:** Pin to required methods + headers. The Authorization-via-localStorage model doesn't strictly need CSRF protection; documenting the choice explicitly.

### Finding PR4 — No `pytest-asyncio` plugin activation (P3)
**Evidence:** `test_docker_executor.py` async tests cannot run locally — pre-existing pytest config gap.
**Why it matters:** Real async coverage is partial.
**Recommended fix:** Add `pytest-asyncio` mode = auto to `pyproject.toml`/`setup.cfg`.

---

# Terraform Runtime Readiness Score (/10)

**Score: 2/10**

Reasoning: The substrate (jobs, locks, credentials, hash-bound approvals, release candidates, event log, policy gates) is real and tested. **None of it is wired into an executor that does not exist.** The Terraform-specific blockers (no executor, no AWS credentials, no plan-hash linkage, no typed-confirmation destroy, no environment-scoped state key, no plan-time-vs-apply-time gate) are all P0. A 2 reflects: scaffolding is competent, runtime is zero.

# Production Readiness Score (/10)

**Score: 4/10**

Reasoning: Auth + per-tenant authz + encrypted credentials + durable jobs are production-shape. JWT default not fatal, no admin kill switch, no log retention, frontend tokens in localStorage, shutdown grace mismatch, dual artifact-store consistency hazard. Solid demo platform; would not pass a production-readiness review for handling real infrastructure mutation.

# Governance Readiness Score (/10)

**Score: 4/10**

Reasoning: The MODEL is excellent — release candidates with immutable snapshots, hash-bound approvals, drift detection, edit-invalidates-approval. The WIRING is missing: no execution path checks a release candidate, no workflow event is emitted in production, mark_executed is never called, the release-level approval is not its own auditable row, the dual artifact store can desync approval state from live content. Decorative governance is worse than no governance — it implies enforcement that isn't there.

# Security Readiness Score (/10)

**Score: 6/10**

Reasoning: Encryption-at-rest (Fernet + rotation), runtime-only credential hydration, log redaction filter, secret-key scrub on every state write — all solid. Deducted for: JWT default warn-only, AUTH_ALLOW_DEV_FALLBACK warn-only, git-error token leak path, ADMIN-stub no-op, no AWS credential model, no STS / assume-role pattern, localStorage tokens, no CSRF strategy documented. Defensible base, several real gaps.

# Multi-tenant Readiness Score (/10)

**Score: 7/10**

Reasoning: `Task.project_id` NOT NULL + schema-guard enforced; legacy routes gated; WS authenticated; per-project run-lock at DB layer; cross-project 404-not-403. Deducted for: claim query optimal but not `SKIP LOCKED` (perf, not correctness); release evaluate isn't atomic with edits (Finding C2); the OWNER self-heal-from-dependency adds an audit-trail wart; no per-environment isolation tied to AWS accounts.

---

# Terraform Executor Go/No-Go Decision

## **NO-GO**

### Exact blockers (P0 only — every one of these MUST close before TerraformExecutor):

1. **Finding S2** — No AWS credential storage / runtime injection. Executor has no way to authenticate to AWS.
2. **Finding R2** — No execution path consumes a `ReleaseCandidate`. Building Terraform on top would re-create the exact "decorative governance" failure mode the previous audit blocked on.
3. **Finding E1** — `WorkflowEventService` is never called. Apply would have no audit trail.
4. **Finding P1** — `ExecutionPolicy` gates are never invoked. The protection layer exists but is unreachable.
5. **Finding T5** — No plan-hash linkage between `terraform plan` output and the release candidate. `stale_plan_gate` is unusable.
6. **Finding T6** — No typed-confirmation gate for `terraform destroy`. Irreversible operations are protected only by route-level role check.
7. **Finding J2** — Worker shutdown grace (30 s) is dramatically shorter than apply duration (40 min). Mid-apply orphans get re-queued and re-run; for Terraform this means re-`apply` — duplicate resource creation risk.
8. **Finding J4** — Cancellation does not terminate the underlying subprocess. "User cancelled the apply" returns 200 while AWS resources continue being created.

---

## What must be completed before TerraformExecutor

Listed in dependency order. Each item is required; the executor cannot ship without the full set.

### Substrate (closes the wiring gaps)

1. **Emit workflow events from every state transition.** WorkflowOrchestrationService start/select-plan/run-phase, releases.py approve/reject, execution_worker supervised job lifecycle. Treat `Workflow.current_phase` as derived. [Finding E1]
2. **Wire `ExecutionPolicy.evaluate(ctx, terraform_apply_policy())` into the future Terraform handler as a non-bypassable pre-flight.** Implement it as a decorator or base class so a handler cannot omit it. [Finding P1]
3. **Make `ReleaseCandidate` the unit of execution.** The Terraform handler must take a `release_candidate_id` in `execution_context`, look it up, call `require_executable_candidate`, refuse on `executable=False`. [Finding R2]
4. **Bridge `Task.workflow_state["artifacts"]` ↔ `Artifact` rows.** The artifact-edit PATCH endpoint must upsert the `Artifact` row in the same transaction so approval invalidation fires immediately. Or eliminate the dual store entirely. [Finding L2]
5. **Persist release-level approval as a row.** Either `release_approvals` table or a fully-populated `candidate_metadata.approval_decision_id` + audit fields. [Finding AP2]
6. **Call `ReleaseService.mark_executed` from the executor's success path.** Wire the lifecycle. [Finding R3]

### AWS credentials & isolation (closes the AWS-side gaps)

7. **Implement `aws_iam` provider end-to-end.** Either long-lived keys (with strong rotation) or — preferred — role-arn + external-id with STS AssumeRole at apply time. Add the credential payload schema + the runtime injection helper. [Finding S2, AW2]
8. **Add `Project.aws_account_id` + `Project.aws_default_region` + `Project.environment` as first-class columns.** Validate format on insert. Used by the environment + AWS-account isolation gates. [Finding AW3, P4]
9. **Plan/apply hash linkage.** Treat `terraform plan` as a separate job phase that stores `sha256(plan-output)` on the candidate. `terraform_apply` re-plans, compares, calls `stale_plan_gate`. [Finding T5]
10. **Per-environment state key prefix.** Update `backend_injector` to emit `environments/{env}/projects/{project_id}/tasks/{task_id}/terraform.tfstate`. Validate `env` against `Project.environment`. [Finding T4]
11. **Typed-confirmation gate + destroy endpoint requiring it.** [Finding T6]

### Runtime safety

12. **Cancellation hard-kills the subprocess.** Implement `proc.terminate()` → 5s wait → `proc.kill()` in the executor's CancelledError handler. [Finding J4]
13. **Shutdown grace ≥ apply timeout, OR refuse-to-shutdown-while-jobs-active for `terraform_apply` / `terraform_destroy` phases.** Pick one. The audit's "leave running, reaper picks up" semantics MUST NOT apply to terraform apply — that path requires explicit manual-recovery, never auto-retry. [Finding J2]
14. **Secret leakage closure in `_sanitize_git_error`** — apply `log_redaction.redact` to error message before raising. Also redact HTTPException detail in the upstream handler. [Finding S1]
15. **Boot-time hard-raise on JWT_SECRET default + AUTH_ALLOW_DEV_FALLBACK in non-dev env.** [Finding A1, A2]
16. **Boot-time hard-raise on APP_SECRET_KEY unset in non-dev env.** [Finding S4]

### Operational

17. **Project-scoped advisory lock around evaluate-then-execute** (combined with the existing per-project run-lock). [Finding C2]
18. **Cancellation race resolution** in supervisor (succeed wins over late cancel). [Finding CN3]

---

## What can be completed after TerraformExecutor

These improve quality but do not block the first safe apply:

* `ADMIN` role + admin kill-switch endpoint. [Findings Z1, O2]
* Cost-ceiling gate. [Finding P2/CG1]
* Move OWNER self-heal out of the auth dependency to bootstrap-only. [Finding Z2]
* `FOR UPDATE SKIP LOCKED` in claim_next_job for multi-process worker scale. [Finding M3]
* Dedicated `execution_logs` table; remove logs from `workflow_state`. [Finding D4]
* Retention reapers for execution_jobs / sessions / events. [Finding D3]
* httpOnly cookie for refresh token. [Finding PR2]
* CORS lockdown; CSRF documentation. [Finding PR3]
* `Workflow.current_phase` removal / reconciliation with event log. [Finding E2, W2]
* Real-Postgres integration test job. [Finding PR1]
* `pytest-asyncio` activation. [Finding PR4]
* User column boolean migration. [Finding D1]
* Email verification enforcement. [Finding D1-adjacent]
* Boot-time `TF_STATE_BUCKET` reachability check. [Finding T3]
* Cost-explorer polling for spend-rate detection. [Finding CG2]
* Migration runbook. [Finding O3]
* Request-id middleware. [Finding O4]

---

## Recommended next implementation phase

### Phase 6 — Executor Substrate Wiring (no Terraform yet)

**Goal:** Close every P0 wiring/gap finding so that when TerraformExecutor lands in Phase 7, every safety mechanism is engaged by default — the executor cannot ship without exercising the gates.

Concrete deliverables, in order (each a reviewable PR):

1. **6a — Workflow event emission.** Add event-emission calls into WorkflowOrchestrationService, releases.py, execution_worker supervisor. Treat event log as authoritative; `Workflow.current_phase` becomes a denormalised cache. Migration not required (table exists).
2. **6b — Artifact-edit ↔ Artifact-row bridge.** PATCH `/api/tasks/{id}/artifacts` upserts `Artifact` rows. Eliminate desync. Add tests proving an edit-after-approval flips `approval_state` immediately.
3. **6c — Release lifecycle wiring.** Add a "ReleaseExecutionHandler" base class that the future TerraformExecutor inherits — its `pre_flight()` runs `require_executable_candidate` + `evaluate(ctx, policy)`; its success path runs `mark_executed`. Wire docker_build handler too (best-effort opt-in, surfacing the same gate UI so users see how Terraform will behave).
4. **6d — AWS credential model.** `aws_iam` provider in CredentialsService, with role-arn + external-id payload. Add `Project.aws_account_id / aws_default_region / environment` columns + migration. STS-AssumeRole helper that returns a session for use in subprocess env. No subprocess yet — just the credential plumbing + tests.
5. **6e — Subprocess hard-kill primitives in DockerExecutor.** Implement the SIGTERM/SIGKILL pattern in a shared `subprocess_helper`; cancellation tests prove process exit. This is the template TerraformExecutor will copy.
6. **6f — Shutdown / reap policy split by phase.** `terraform_apply` / `terraform_destroy` reap goes to `failed` (not `pending`); add a "force retry" admin endpoint with explicit confirmation. Tests prove the safe-by-default behaviour.
7. **6g — Stale-plan plumbing.** Stub a `terraform_plan` handler that produces a deterministic hash (mocked terraform output is fine), stores it on the candidate. Wire `stale_plan_gate` end-to-end against this stub. When TerraformExecutor lands in Phase 7, swap the stub for real `terraform plan`.
8. **6h — Boot-time hard-raises.** JWT_SECRET default, AUTH_ALLOW_DEV_FALLBACK in non-dev, APP_SECRET_KEY unset in non-dev. Each gated by `APP_ENV != "development"`. Tests prove the boot failure mode.
9. **6i — Git-error token redaction.** `_sanitize_git_error` calls `log_redaction.redact`; HTTPException middleware redacts response bodies. Test against a contrived stderr containing a PAT.

**Phase 7 — TerraformExecutor** then becomes a clean layer ON TOP of all of the above: it inherits ReleaseExecutionHandler, picks up every gate automatically, fetches AWS credentials from the encrypted store via STS, runs plan → store hash → apply with hash verification, cancellation hard-kills, and on success calls `mark_executed`. Everything important is enforced by the substrate, not by the executor's own discipline.

If Phase 6 is done well, Phase 7 is small. If Phase 6 is skipped or shortcut, Phase 7 will land with the same fundamental hole the original audit blocked on: gates exist, executor forgets to call one.

---

**End of audit.**
