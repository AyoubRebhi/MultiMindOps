# Infrastructure Lifecycle Management

The **final operational phase** (after Monitoring). It lets engineers safely
control already-deployed infrastructure: inspect state + resources, review
recovery history, retry a failed bootstrap, and destroy — all without leaving the
existing workflow.

It is **pure composition** over capabilities the platform already has (destroy,
monitoring, recovery, automatic import) plus one new append-only history store.
No new orchestration engine, no workers, no Kubernetes operators. **GitHub
Actions remains the only execution engine; the backend never runs Terraform.**

Module: [`backend/app/services/infrastructure_lifecycle/`](../backend/app/services/infrastructure_lifecycle)
· Panel: [`WorkflowInfrastructureLifecyclePhase.jsx`](../frontend/src/pages/workflow/WorkflowInfrastructureLifecyclePhase.jsx)
· Tests: [`backend/tests/test_infrastructure_lifecycle.py`](../backend/tests/test_infrastructure_lifecycle.py)

---

## 1. Architecture

```
                 Frontend: Infrastructure Lifecycle dashboard
   Status · Terraform State · Recovery · Resources · Actions · Monitoring · History
                                  │
            GET .../lifecycle     │  POST .../lifecycle/retry-bootstrap
                                  │  POST .../lifecycle/destroy
                                  ▼
                 InfrastructureLifecycleService  (composition only)
        ┌──────────────┬──────────────┬───────────────┬────────────────┐
        ▼              ▼              ▼               ▼                ▼
  WorkflowMonitoring  Infrastructure  Artifact      resource_inventory  LifecycleEvent
  Service._observe    DestroyService  Persistence   (parse .tf config)  Service
  (read-only runs)    (.run/.guard)   (recovery /                       (append-only
                                       import JSON)                       history)
        │                                                                    │
        ▼                                                                    ▼
  bootstrap/deploy/destroy runs                                 immutable event rows
        │
        ▼
  GitHub Actions  ──  the ONLY execution engine (terraform apply/destroy)
```

Actions dispatch GitHub Actions workflows and are then **observed read-only** —
identical to how bootstrap and deploy are monitored. The backend orchestrates;
it never executes Terraform.

---

## 2. Every modified / added file

**Backend (added):**

| File | Purpose |
|---|---|
| `models/lifecycle_event.py` | `InfrastructureLifecycleEvent` — append-only history table. |
| `schemas/infrastructure_lifecycle_phase.py` | Dashboard response + action request/response + event-type constants. |
| `services/infrastructure_lifecycle/lifecycle_event_service.py` | Append-only record + list + dedup. No update/delete. |
| `services/infrastructure_lifecycle/resource_inventory.py` | Parse generated Terraform → inventory grouped by AWS service; parse state location. Pure. |
| `services/infrastructure_lifecycle/lifecycle_service.py` | `get_status` (aggregate), `retry_bootstrap`, `request_destroy`. |
| `services/infrastructure_lifecycle/__init__.py` | Package exports. |
| `tests/test_infrastructure_lifecycle.py` | The 8 required test areas. |

**Backend (edited, additive only):**

| File | Change |
|---|---|
| `models/__init__.py` | Register the new model so its table is created. |
| `api/routes/projects.py` | `GET /lifecycle`, `POST /lifecycle/retry-bootstrap`, `POST /lifecycle/destroy` + `_can_manage_infrastructure` helper. |

**Frontend (added):** `WorkflowInfrastructureLifecyclePhase.jsx`.

**Frontend (edited, additive only):** `services/api/workflowApi.js` (mapper + 3 methods), `hooks/useWorkflowRun.js` (`useLifecyclePhase`), `utils/constants.js` (phase meta / view / status meta), `pages/workflow/WorkflowRunPage.jsx` (the `lifecycle` view).

No existing workflow phase, AI generation, monitoring, Terraform/GitHub-Actions
generation, repository installation, or automatic-import code was modified.

---

## 3. How the lifecycle layer integrates with the existing workflow

It does **not** create a new workflow or orchestration engine. It is a new
*view* on the existing workflow, reachable at `…/run/{workflowId}/lifecycle`
(registered in `WORKFLOW_PHASE_VIEW` + `CANONICAL_PHASE_ORDER` after Monitoring).
The service composes the existing services:

* **status / runs** ← `WorkflowMonitoringService._observe` (read-only),
* **destroy** ← `InfrastructureDestroyService.run` / `.infrastructure_state`,
* **state + inventory** ← `ArtifactPersistenceService.get_terraform_files`,
* **recovery / import** ← the existing `recovery.json` / `import_recovery.json` artifacts,
* **retry** ← `dispatch_workflow` (the same client repository-installation uses).

The generation lifecycle (`phases_state`) is untouched.

---

## 4. How infrastructure history is stored

Every lifecycle action appends ONE immutable `InfrastructureLifecycleEvent` row
(`BOOTSTRAP_RETRY`, `DESTROY_REQUESTED`, `DESTROY_COMPLETED`, `DESTROY_FAILED`,
`IMPORT_COMPLETED`, `RECOVERY_COMPLETED`, `BOOTSTRAP_RETRY_FAILED`). The table
follows the same append-only convention as `ArtifactVersion` / `ArtifactApproval`
— **there is no update or delete API; history is never overwritten.**

Outcomes that happen in other services (automatic import, recovery diagnosis,
destroy run completion) are **reconciled into history on read**, idempotently:
each carries a `dedup_key`, and `record(...)` returns the existing row instead of
inserting a duplicate. So "every recovery attempt" appears without modifying the
import/recovery services, and re-reading the dashboard never doubles an event.

---

## 5. How destroy remains safe

* **Two confirmations.** The API requires BOTH `confirm` and
  `acknowledge_data_loss` to be true; the UI gates the destroy button behind an
  acknowledgement checkbox inside an explicit dialog that spells out the
  consequences. Missing either ⇒ `blocked` (HTTP 409).
* **Never automatic.** Destroy only runs from a deliberate, confirmed request.
* **Never after a bootstrap failure.** Blocked when the last bootstrap run
  concluded failure.
* **Never during recovery / a run in flight.** Blocked while a bootstrap run is
  in an active GitHub Actions state.
* **Never twice.** Blocked once the infrastructure is already destroyed.
* **Permission-gated.** Only DEVELOPER / CLOUD_ARCHITECT / OWNER / ADMIN may
  destroy (server-side `require_project_contributor`); VIEWER is read-only.
* **Backend never runs Terraform.** Destroy dispatches `destroy.yml`; GitHub
  Actions runs `terraform destroy`.

---

## 6. How monitoring continues to observe destroy executions

The lifecycle layer reuses `WorkflowMonitoringService._observe(..., "destroy")`
— the exact read-only path that observes `bootstrap.yml` and `deploy.yml`. The
destroy run is surfaced as the same `PipelineRunView` type as bootstrap/deploy,
in the dashboard's Monitoring section. **No new monitoring system is introduced**;
destroy executions appear exactly like the other pipelines and reconcile their
terminal state through the existing destroy/monitoring machinery.

---

## 7. Permissions

| Role | Inspect dashboard | Retry bootstrap | Destroy |
|---|---|---|---|
| OWNER / ADMIN / CLOUD_ARCHITECT / DEVELOPER | ✓ | ✓ | ✓ |
| VIEWER (read-only) | ✓ | ✗ | ✗ |

The GET endpoint computes `can_manage` so the UI disables the actions for
read-only users; the action endpoints additionally enforce it server-side with
`require_project_contributor`.

---

## 8. Resource inventory & state — a note on the source

The inventory and state section are derived from the generated Terraform
**configuration** (the `.tf` artifacts in the DB), grouped by AWS service. The
backend deliberately does **not** read the remote S3 state or query AWS — it
never runs Terraform/AWS (GitHub Actions is the only execution engine). So
"managed resources" is the declared, execution-free resource set; "imported
resources" comes from the automatic-import record; and live `drift` is reported
as `unavailable` (it would require a `terraform plan` against real state, which
only GitHub Actions performs).
