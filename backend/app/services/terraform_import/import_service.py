"""TerraformImportService — automatic Terraform import recovery.

Turns a failed ``terraform apply`` (resources already exist in AWS) into the
deterministic, hands-off sequence::

    detect → safety-check → import → refresh → plan → apply

so the engineer never runs ``terraform import`` by hand. It is a self-contained,
modular service: it does NOT live inside workflow orchestration, and the
terraform runner is INJECTED (the default is a subprocess runner; tests pass a
fake), so the recovery logic is unit-testable without a terraform binary or AWS.

Guarantees
----------
* Idempotent — resources already in state are skipped (``terraform state list``
  is consulted first, and an "already managed" import error is treated as a
  skip), so a re-run imports nothing and never duplicates or corrupts state.
* Safe — every resource is validated (type, address, identifier, AWS account,
  AWS region, project ownership) BEFORE any import; a wrong-account/region
  resource aborts the whole recovery.
* Observable — every step is captured as a structured log entry on the result.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from backend.app.models.project import Project
from backend.app.models.workflow import Workflow
from backend.app.services.terraform_import.failure_parser import parse_failure
from backend.app.services.terraform_import.models import (
    ABORTED_VALIDATION,
    APPLY_ARGS,
    FAILED,
    IMPORTED,
    INIT_ARGS,
    PLAN_ARGS,
    REFRESH_ARGS,
    SKIPPED_ALREADY_MANAGED,
    STATE_LIST_ARGS,
    STATUS_ABORTED,
    STATUS_FAILED,
    STATUS_NOOP,
    STATUS_PARTIAL,
    STATUS_RECOVERED,
    CommandResult,
    ImportableResource,
    ImportOutcome,
    ImportRecoveryResult,
    import_args,
    import_command_str,
)
from backend.app.services.terraform_import.safety import (
    GLOBAL_ABORT_CATEGORIES,
    ImportSafetyContext,
    validate_resource,
)

logger = logging.getLogger(__name__)

# A terraform runner: given (args, working_dir) it runs terraform and returns the
# result. Injected so tests never touch a real binary or AWS.
TerraformRunner = Callable[[List[str], Path], CommandResult]

_RECORD_TYPE = "infrastructure_import"
_RECORD_SUBTYPE = "import_recovery.json"
_PHASE = "TERRAFORM_IMPORT_RECOVERY"

# Import-error fragments that mean "already in state" → treat as an idempotent skip.
_ALREADY_MANAGED_FRAGMENTS = (
    "resource already managed by terraform",
    "already managed by terraform",
    "already exists in the state",
    "already in the state",
)


class TerraformBinaryMissingError(RuntimeError):
    """Raised by the default runner when the ``terraform`` binary is unavailable."""


def _make_subprocess_runner(timeout: int) -> TerraformRunner:
    """Build the default subprocess-backed terraform runner.

    Uses the project's terraform subprocess environment (AWS credentials +
    region) — the SAME env the validate/plan pipeline uses — so imports run
    against the real remote backend. Imported lazily to avoid an import cycle.
    """

    def _run(args: List[str], working_dir: Path) -> CommandResult:
        binary = shutil.which("terraform")
        if not binary:
            raise TerraformBinaryMissingError(
                "The 'terraform' binary was not found on PATH; cannot run import recovery."
            )
        from backend.app.services.terraform_pipeline.pipeline_service import (
            terraform_subprocess_env,
        )

        completed = subprocess.run(
            [binary, *args],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=terraform_subprocess_env(),
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    return _run


class TerraformImportService:
    """Automatic Terraform import recovery (modular, runner-injected)."""

    def __init__(
        self,
        runner: Optional[TerraformRunner] = None,
        *,
        command_timeout: int = 900,
        do_apply: bool = True,
    ) -> None:
        self._runner = runner or _make_subprocess_runner(command_timeout)
        self._do_apply = do_apply

    # ─── Detection ─────────────────────────────────────────────────────────────

    @staticmethod
    def detect(failure_text: Optional[str]) -> List[ImportableResource]:
        """Parse a terraform failure blob into importable resources (read-only)."""
        return parse_failure(failure_text)

    @staticmethod
    def build_import_command(resource: ImportableResource) -> str:
        return import_command_str(resource.terraform_address, resource.aws_identifier)

    # ─── Core recovery ─────────────────────────────────────────────────────────

    def recover_from_failure(
        self,
        *,
        working_dir: Path,
        failure_text: str,
        safety: ImportSafetyContext,
        do_apply: Optional[bool] = None,
    ) -> ImportRecoveryResult:
        """Detect importable resources from ``failure_text`` then recover them."""
        return self.recover(
            working_dir=working_dir,
            resources=self.detect(failure_text),
            safety=safety,
            do_apply=do_apply,
        )

    def recover(
        self,
        *,
        working_dir: Path,
        resources: List[ImportableResource],
        safety: ImportSafetyContext,
        do_apply: Optional[bool] = None,
    ) -> ImportRecoveryResult:
        """Run the full import-recovery sequence and return a structured result."""
        start = time.perf_counter()
        logs: List[dict] = []
        do_apply = self._do_apply if do_apply is None else do_apply

        def log(step: str, message: str, **fields) -> None:
            logs.append({"step": step, "message": message, **fields})
            logger.info("[TFImport] %s — %s", step, message)

        log(
            "detect",
            f"{len(resources)} importable resource(s) detected",
            resources=[r.terraform_address for r in resources],
        )
        if not resources:
            return self._finish(STATUS_NOOP, start, logs)

        # 1. Safety — validate every resource; a wrong account/region aborts ALL.
        validated: List[tuple[ImportableResource, Optional[object]]] = []
        global_abort = None
        for r in resources:
            violation = validate_resource(r, safety)
            validated.append((r, violation))
            if violation and violation.category in GLOBAL_ABORT_CATEGORIES:
                global_abort = violation
        if global_abort is not None:
            log("safety", f"ABORT — {global_abort.message}", category=global_abort.category)
            aborted = [
                ImportOutcome(
                    r, ABORTED_VALIDATION,
                    message=(v.message if v else "aborted: global safety violation"),
                )
                for r, v in validated
            ]
            result = self._finish(STATUS_ABORTED, start, logs, aborted=aborted)
            result.error = global_abort.message
            return result

        # 2. terraform init — REAL backend (import + apply read/write remote state).
        init = self._runner(INIT_ARGS, working_dir)
        log("init", "terraform init " + ("ok" if init.ok else "FAILED"), returncode=init.returncode)
        if not init.ok:
            result = self._finish(STATUS_FAILED, start, logs)
            result.error = f"terraform init failed: {init.output[:500]}"
            return result

        # 3. Idempotency — what is already in state?
        existing = self._state_addresses(working_dir)
        log("state", f"{len(existing)} resource(s) already in terraform state")

        imported: List[ImportOutcome] = []
        skipped: List[ImportOutcome] = []
        failed: List[ImportOutcome] = []
        aborted: List[ImportOutcome] = []

        # 4. Import each resource.
        for r, violation in validated:
            if violation is not None:  # per-resource (non-global) violation → skip
                aborted.append(ImportOutcome(r, ABORTED_VALIDATION, message=violation.message))
                log("safety", f"skip {r.terraform_address}: {violation.message}",
                    category=violation.category)
                continue
            if r.terraform_address in existing:  # idempotent skip
                skipped.append(ImportOutcome(
                    r, SKIPPED_ALREADY_MANAGED, message="already in terraform state"))
                log("import", f"skip {r.terraform_address}: already managed")
                continue

            cmd = import_command_str(r.terraform_address, r.aws_identifier)
            t0 = time.perf_counter()
            res = self._runner(import_args(r.terraform_address, r.aws_identifier), working_dir)
            dms = int((time.perf_counter() - t0) * 1000)

            if res.ok:
                imported.append(ImportOutcome(r, IMPORTED, command=cmd,
                                              message="import successful", duration_ms=dms))
                existing.add(r.terraform_address)
                log("import", f"imported {r.terraform_address}", command=cmd,
                    result="ok", aws_identifier=r.aws_identifier, duration_ms=dms)
            elif _is_already_managed(res.output):
                skipped.append(ImportOutcome(r, SKIPPED_ALREADY_MANAGED, command=cmd,
                                             message="already managed by terraform", duration_ms=dms))
                existing.add(r.terraform_address)
                log("import", f"skip {r.terraform_address}: already managed (race)", command=cmd)
            else:
                failed.append(ImportOutcome(r, FAILED, command=cmd,
                                            message=res.output[:500], duration_ms=dms))
                log("import", f"FAILED {r.terraform_address}", command=cmd,
                    result="error", error=res.output[:300], duration_ms=dms)

        imported_count = len(imported)

        # 5. If ANY import failed, do not refresh/plan/apply — leave state as-is.
        if failed:
            status = STATUS_PARTIAL if imported else STATUS_FAILED
            log("summary",
                f"{len(failed)} import(s) failed — skipping plan/apply",
                imported=imported_count, failed=len(failed), skipped=len(skipped))
            return self._finish(status, start, logs, imported=imported, skipped=skipped,
                                failed=failed, aborted=aborted, imported_count=imported_count)

        # 6. Refresh → plan → apply (retry the deployment from reconciled state).
        refresh = self._runner(REFRESH_ARGS, working_dir)
        refresh_ok = refresh.ok
        log("refresh", "refresh-only " + ("ok" if refresh_ok else "FAILED"))

        plan = self._runner(PLAN_ARGS, working_dir)
        plan_ok = plan.ok
        log("plan", "plan " + ("ok" if plan_ok else "FAILED"))

        apply_ok: Optional[bool] = None
        if do_apply and refresh_ok and plan_ok:
            apply = self._runner(APPLY_ARGS, working_dir)
            apply_ok = apply.ok
            log("apply", "apply " + ("ok" if apply_ok else "FAILED"))

        if not refresh_ok or not plan_ok:
            status = STATUS_FAILED
        elif do_apply:
            status = STATUS_RECOVERED if apply_ok else STATUS_FAILED
        else:
            status = STATUS_RECOVERED  # plan-only recovery (apply deferred)

        log("summary",
            f"status={status} imported={imported_count} skipped={len(skipped)}",
            imported=imported_count, skipped=len(skipped), aborted=len(aborted))
        return self._finish(
            status, start, logs, imported=imported, skipped=skipped, aborted=aborted,
            refresh_ok=refresh_ok, plan_ok=plan_ok, apply_ok=apply_ok,
            imported_count=imported_count,
        )

    # ─── Workflow integration (persist outcome; never modifies orchestration) ──

    def recover_for_workflow(
        self,
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        failure_text: str,
        working_dir: Path,
        safety: Optional[ImportSafetyContext] = None,
        do_apply: Optional[bool] = None,
    ) -> ImportRecoveryResult:
        """Recover for a workflow + persist the outcome (success OR failure).

        Persists an ``infrastructure_import`` recovery artifact and a diagnostic
        phase marker so the surface can show "recovered → continue" or
        "failed → retry". Does NOT touch the orchestration engine.
        """
        safety = safety or self._safety_for_project(project)
        result = self.recover_from_failure(
            working_dir=working_dir, failure_text=failure_text,
            safety=safety, do_apply=do_apply,
        )
        self._persist(db, project=project, workflow=workflow, result=result)
        return result

    @staticmethod
    def _safety_for_project(project: Project) -> ImportSafetyContext:
        """Derive the safety boundary from the project (read-only)."""
        from backend.app.services.terraform_generation.utils.naming import (
            sanitize_resource_name,
        )

        prefix = sanitize_resource_name(project.name, fallback="devsecops-app")
        return ImportSafetyContext(
            project_id=project.id,
            allowed_name_prefix=prefix,
        )

    # ─── Internals ─────────────────────────────────────────────────────────────

    def _state_addresses(self, working_dir: Path) -> set[str]:
        """Addresses already tracked in state (``terraform state list``)."""
        result = self._runner(STATE_LIST_ARGS, working_dir)
        if not result.ok:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    @staticmethod
    def _finish(
        status: str,
        start: float,
        logs: List[dict],
        *,
        imported: Optional[List[ImportOutcome]] = None,
        skipped: Optional[List[ImportOutcome]] = None,
        failed: Optional[List[ImportOutcome]] = None,
        aborted: Optional[List[ImportOutcome]] = None,
        refresh_ok: Optional[bool] = None,
        plan_ok: Optional[bool] = None,
        apply_ok: Optional[bool] = None,
        imported_count: int = 0,
    ) -> ImportRecoveryResult:
        return ImportRecoveryResult(
            status=status,
            imported=imported or [],
            skipped=skipped or [],
            failed=failed or [],
            aborted=aborted or [],
            refresh_ok=refresh_ok,
            plan_ok=plan_ok,
            apply_ok=apply_ok,
            imported_count=imported_count,
            duration_ms=int((time.perf_counter() - start) * 1000),
            logs=logs,
        )

    @staticmethod
    def _persist(
        db: Session,
        *,
        project: Project,
        workflow: Workflow,
        result: ImportRecoveryResult,
    ) -> None:
        """Upsert the import-recovery artifact + a phase marker. Best-effort.

        Never overwrites Terraform artifacts (own ``infrastructure_import`` type).
        A persistence failure must not affect the recovery outcome.
        """
        try:
            from datetime import datetime, timezone

            from backend.app.services.core.artifact_persistence_service import (
                ArtifactPersistenceService,
            )

            ArtifactPersistenceService.upsert_artifact(
                db,
                project_id=project.id,
                workflow_id=workflow.id,
                artifact_type=_RECORD_TYPE,
                artifact_subtype=_RECORD_SUBTYPE,
                content=json.dumps(result.to_dict(), indent=2, default=str),
                generated_by_agent="TerraformImportService",
                validation_status="passed",
            )
            phases = dict(workflow.phases_state or {})
            phases[_PHASE] = {
                "status": result.status,
                "imported_count": result.imported_count,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            workflow.phases_state = phases
            db.commit()
        except Exception as exc:  # noqa: BLE001 — persistence is non-critical
            logger.warning(
                "[TFImport] persist failed project=%s: %s",
                project.id, exc.__class__.__name__,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass


def _is_already_managed(output: str) -> bool:
    low = (output or "").lower()
    return any(fragment in low for fragment in _ALREADY_MANAGED_FRAGMENTS)
