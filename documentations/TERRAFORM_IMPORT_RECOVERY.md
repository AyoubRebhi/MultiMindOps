# Automatic Terraform Import Recovery

When `terraform apply` fails because AWS resources **already exist**
(`RepositoryAlreadyExistsException`, `EntityAlreadyExists`,
`ResourceInUseException`/cluster-exists, `BucketAlreadyOwnedByYou`, …), the
platform adopts those resources into Terraform state and retries the deployment
— so **no engineer ever runs `terraform import` by hand**.

It is implemented as a **standalone, modular service** (`TerraformImportService`)
with an **injectable terraform runner**. It is NOT embedded in workflow
orchestration; it does not modify AI generation, monitoring, or the existing
workflow execution.

Module: [`backend/app/services/terraform_import/`](../backend/app/services/terraform_import)
· Tests: [`backend/tests/test_terraform_import.py`](../backend/tests/test_terraform_import.py)

---

## 1. Architecture of the import flow

```
            terraform apply FAILS ("...AlreadyExists...")
                          │
                          ▼
            ┌─────────────────────────────┐
            │  failure_parser.parse_failure│   detect importable resources
            │  • pair "with <address>"     │   → [ImportableResource(
            │    with its AWS error block  │        terraform_address,
            │  • extract AWS import id     │        resource_type,
            │  • supported types only      │        aws_identifier ), ...]
            └─────────────┬───────────────┘
                          ▼
            ┌─────────────────────────────┐
            │  safety.validate_resource    │   verify BEFORE importing:
            │  type · address · identifier │   project_id (ownership),
            │  AWS account · AWS region    │   account, region
            └─────────────┬───────────────┘
                wrong account/region ──────────────►  ABORT (import nothing)
                          │ ok
                          ▼
            ┌─────────────────────────────┐
            │  terraform init  (real S3 backend)        │
            ├─────────────────────────────┤
            │  terraform state list   ◄── idempotency: skip addresses          │
            │                              already in state                     │
            ├─────────────────────────────┤
            │  for each resource:          │
            │     terraform import ADDR ID │   ok → imported
            │                              │   "already managed" → skipped
            │                              │   error → failed
            └─────────────┬───────────────┘
                 any failed ──────────────►  PARTIAL / FAILED (do NOT apply)
                          │ all ok
                          ▼
            terraform apply -refresh-only  →  terraform plan  →  terraform apply
                          │
                          ▼
                   RECOVERED → deployment continues
                          │
                          ▼
            persist infrastructure_import / import_recovery.json
            (success OR failure → engineer can retry)
```

Files:

| File | Responsibility |
|---|---|
| `models.py` | Typed value objects, supported-type allow-list, single source of truth for every terraform command's arguments. |
| `failure_parser.py` | Parse the failure blob → `ImportableResource[]` (address + AWS import id). Pure. |
| `safety.py` | `ImportSafetyContext` + `validate_resource` (type / address / identifier / account / region / ownership). Pure. |
| `import_service.py` | `TerraformImportService` — orchestrates detect → safety → import → refresh → plan → apply through the injected runner; structured logging; persistence. |

The terraform runner is `Callable[[args, working_dir], CommandResult]`. The
default is a subprocess runner that reuses the existing
`terraform_subprocess_env()` (AWS creds + region). Tests inject a fake runner, so
the entire recovery is unit-tested without a terraform binary or AWS.

---

## 2. Supported AWS resources

`aws_ecr_repository`, `aws_iam_role`, `aws_eks_cluster`, `aws_eks_node_group`,
`aws_ecs_cluster`, `aws_s3_bucket`, `aws_security_group`, `aws_lb`,
`aws_lb_target_group`, `aws_subnet`, `aws_vpc`, `aws_internet_gateway`,
`aws_route_table`.

Any resource type **outside** this allow-list is never imported (a
`SafetyViolation(unsupported_type)` skips it). Import identifiers are extracted
per type — names for name-keyed resources (ECR/IAM/EKS/ECS/S3), AWS ids for
`vpc-`/`subnet-`/`sg-`/`igw-`/`rtb-` resources, and ARNs for `aws_lb` /
`aws_lb_target_group`.

---

## 3. How state consistency is maintained

* **Real remote backend.** `terraform init` runs against the project's real S3
  backend (no `-backend=false`), so imports and the retry apply read/write the
  same durable, per-project state object — never throwaway local state.
* **Refresh before re-plan.** After imports, `terraform apply -refresh-only`
  reconciles state with the live resources, then `plan` then `apply` run from
  that reconciled state.
* **No apply on partial failure.** If *any* import fails, the service stops at
  `partial`/`failed` and **does not** refresh/plan/apply — state is left exactly
  as the successful imports made it, never advanced from an inconsistent base.
* **Single-writer semantics.** The backend's DynamoDB lock (from the S3 backend
  config) serialises concurrent operations on the same state key.

---

## 4. How duplicate imports are avoided (idempotency)

1. **Pre-check `terraform state list`.** Before importing, the service reads the
   addresses already in state and **skips** any resource already present.
2. **"Already managed" is a skip, not an error.** If an import still races and
   returns *"Resource already managed by Terraform"*, it is recorded as
   `skipped_already_managed`, not `failed`.
3. **De-duplicated detection.** The parser de-duplicates by terraform address, so
   one failure blob never yields the same address twice.

Net effect: a **second run imports nothing, duplicates nothing, and corrupts
nothing** — verified by `test_idempotent_rerun_imports_nothing_the_second_time`
and `test_already_imported_is_skipped`.

---

## 5. How the retry mechanism works

After all detected resources are imported (or were already managed):

1. `terraform apply -refresh-only -auto-approve` — reconcile state ↔ reality.
2. `terraform plan` — confirm the configuration now converges.
3. `terraform apply -auto-approve` — complete the deployment.

Result statuses:

| Status | Meaning |
|---|---|
| `recovered` | imports done (or all already managed) **and** the retry apply succeeded → deployment continues, no manual restart |
| `partial` | some imports succeeded, some failed → apply skipped; engineer can retry |
| `failed` | init/import/plan/apply failed → persisted for retry |
| `aborted` | wrong AWS account/region → nothing imported |
| `noop` | nothing importable detected |

On both success and failure the outcome is persisted as an
`infrastructure_import` / `import_recovery.json` artifact plus a
`phases_state[TERRAFORM_IMPORT_RECOVERY]` marker (best-effort; **never overwrites
Terraform artifacts**), so the surface can show *"recovered → continue"* or
*"failed → retry"*. Workflow orchestration is untouched.

---

## 6. Safety summary

Before any import, every resource is validated against an `ImportSafetyContext`:

* **type** ∈ supported allow-list,
* **terraform address** is well-formed,
* **identifier** is non-empty and within a safe charset,
* **AWS account** / **AWS region** parsed from ARNs must match the project's
  expected account/region — a mismatch **aborts the entire recovery**,
* **ownership** — the resource name/id must match the project's sanitized name
  prefix, so a resource from another project is never adopted.
