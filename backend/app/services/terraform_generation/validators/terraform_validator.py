"""
TerraformValidator — runs the deterministic pre-apply pipeline.

Stages (in order, fail-fast):

    1. hcl2_parse        — pure-Python python-hcl2 syntactic check. Required.
    2. terraform fmt     — formatting drift check.       (skipped if no `terraform` binary)
    3. terraform init    — local providers; -backend=false. (skipped if no binary)
    4. terraform validate — semantic check.              (skipped if no binary)
    5. tfsec             — security scan.                (skipped if no binary)
    6. checkov           — security scan.                (skipped if no binary)

Tool detection
--------------
Each subprocess validator checks ``shutil.which()`` first. Missing tools mark
that stage as ``skipped`` rather than failing — this lets the pipeline run in
both CI (where tools are installed) and developer workstations (where they may
not be). The orchestrator can still see the per-validator status and decide
whether a "skipped tfsec" should block a production apply.

Isolation
---------
Subprocesses run inside a per-call temp directory with a hard timeout. They
never see the parent process environment beyond PATH and HOME — this keeps
AWS credentials out of validation runs.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from backend.app.services.terraform_generation.validators.models import (
    TerraformSecurityIssue,
    TerraformValidationIssue,
    TerraformValidationResult,
    ValidationSeverity,
    ValidationStatus,
    ValidatorName,
)

logger = logging.getLogger(__name__)


# ── Filename mapping for the orchestrator artifact-key convention ────────────


_ARTIFACT_KEY_TO_FILENAME: Dict[str, str] = {
    "terraform_providers": "providers.tf",
    "terraform_main": "main.tf",
    "terraform_variables": "variables.tf",
    "terraform_tfvars": "terraform.tfvars",
    "terraform_outputs": "outputs.tf",
    "terraform_backend": "backend.tf",
}


# Severity mapping for tfsec / checkov payloads.
_TFSEC_SEVERITY: Dict[str, ValidationSeverity] = {
    "CRITICAL": "critical",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
}
_CHECKOV_SEVERITY: Dict[str, ValidationSeverity] = {
    "CRITICAL": "critical",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
}


class TerraformValidator:
    """
    Validation pipeline. Reusable across renders — holds no per-call state.

    Parameters
    ----------
    timeout_seconds : int
        Per-subprocess hard limit. Defaults to 90s.
    skip_subprocess_validators : bool
        Force-skip every subprocess-backed validator (useful for unit tests
        that only want to exercise hcl2 parsing).
    """

    def __init__(
        self,
        timeout_seconds: int = 90,
        skip_subprocess_validators: bool = False,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.skip_subprocess_validators = skip_subprocess_validators

    # ── Public API ────────────────────────────────────────────────────────

    def validate(
        self,
        artifacts: Mapping[str, str],
    ) -> TerraformValidationResult:
        """
        Run the full pipeline against the rendered Terraform artifacts.

        ``artifacts`` is a mapping {orchestrator_artifact_key: hcl_content}
        — the same shape RenderResult.artifacts uses.
        """
        start = time.perf_counter()
        issues: List[TerraformValidationIssue] = []
        security_issues: List[TerraformSecurityIssue] = []
        validators_run: Dict[ValidatorName, ValidationStatus] = {}
        skipped: List[ValidatorName] = []

        # 1. HCL syntax — pure-Python, always runs ────────────────────────
        hcl_issues, hcl_status = self._run_hcl2_parse(artifacts)
        validators_run["hcl2_parse"] = hcl_status
        issues.extend(hcl_issues)
        if hcl_status == "failed":
            # Bail early — running terraform on un-parseable HCL wastes time
            # and produces redundant error messages.
            return self._finalize(
                issues, security_issues, validators_run, skipped, start
            )

        # 2-6. Subprocess validators (use a single shared working directory)
        if self.skip_subprocess_validators:
            for name in ("terraform_fmt", "terraform_init", "terraform_validate", "tfsec", "checkov"):
                skipped.append(name)  # type: ignore[arg-type]
                validators_run[name] = "skipped"  # type: ignore[index]
            return self._finalize(
                issues, security_issues, validators_run, skipped, start
            )

        with tempfile.TemporaryDirectory(prefix="tfval_") as tmp:
            workdir = Path(tmp)
            self._materialize_artifacts(artifacts, workdir)

            # terraform fmt -check ─────────────────────────────────────────
            issues_, status_ = self._run_terraform_subprocess(
                workdir, ["fmt", "-check", "-recursive"], "terraform_fmt"
            )
            validators_run["terraform_fmt"] = status_
            issues.extend(issues_)
            if status_ == "skipped":
                skipped.append("terraform_fmt")

            # terraform init -backend=false ────────────────────────────────
            issues_, status_ = self._run_terraform_subprocess(
                workdir, ["init", "-backend=false", "-input=false"], "terraform_init"
            )
            validators_run["terraform_init"] = status_
            issues.extend(issues_)
            if status_ == "skipped":
                skipped.append("terraform_init")
            # Without init succeeding, terraform validate will not work.
            init_ok = status_ in ("passed", "warnings", "skipped")

            # terraform validate ───────────────────────────────────────────
            if init_ok:
                issues_, status_ = self._run_terraform_subprocess(
                    workdir, ["validate", "-no-color"], "terraform_validate"
                )
                validators_run["terraform_validate"] = status_
                issues.extend(issues_)
                if status_ == "skipped":
                    skipped.append("terraform_validate")
            else:
                validators_run["terraform_validate"] = "skipped"
                skipped.append("terraform_validate")

            # tfsec ────────────────────────────────────────────────────────
            sec_issues_, status_ = self._run_tfsec(workdir)
            validators_run["tfsec"] = status_
            security_issues.extend(sec_issues_)
            if status_ == "skipped":
                skipped.append("tfsec")

            # checkov ──────────────────────────────────────────────────────
            sec_issues_, status_ = self._run_checkov(workdir)
            validators_run["checkov"] = status_
            security_issues.extend(sec_issues_)
            if status_ == "skipped":
                skipped.append("checkov")

        return self._finalize(issues, security_issues, validators_run, skipped, start)

    # ── Stage 1: HCL syntax (pure Python, always available if hcl2 is) ───

    def _run_hcl2_parse(
        self,
        artifacts: Mapping[str, str],
    ) -> Tuple[List[TerraformValidationIssue], ValidationStatus]:
        try:
            import hcl2  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "[TerraformValidator] python-hcl2 not installed — skipping syntax check"
            )
            return [], "skipped"

        issues: List[TerraformValidationIssue] = []
        for key, content in artifacts.items():
            filename = _ARTIFACT_KEY_TO_FILENAME.get(key, key)
            if filename == "terraform.tfvars":
                # tfvars uses HCL2 too, but hcl2.loads() expects file-like.
                content_for_parse = content
            else:
                content_for_parse = content
            try:
                from io import StringIO
                hcl2.load(StringIO(content_for_parse))  # type: ignore[arg-type]
            except Exception as exc:
                issues.append(
                    TerraformValidationIssue(
                        severity="error",
                        source="hcl2_parse",
                        file=filename,
                        message=f"HCL2 parse error: {exc}",
                        remediation="Check matching braces, quoted strings, and HCL block syntax.",
                    )
                )

        if any(i.severity in ("error", "critical") for i in issues):
            return issues, "failed"
        return issues, "passed"

    # ── Stage 2-4: terraform CLI ─────────────────────────────────────────

    def _run_terraform_subprocess(
        self,
        workdir: Path,
        args: List[str],
        validator_name: ValidatorName,
    ) -> Tuple[List[TerraformValidationIssue], ValidationStatus]:
        binary = shutil.which("terraform")
        if not binary:
            logger.info(
                "[TerraformValidator] terraform binary not found — skipping %s",
                validator_name,
            )
            return [], "skipped"

        cmd = [binary, *args]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=self._isolated_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return (
                [
                    TerraformValidationIssue(
                        severity="error",
                        source=validator_name,
                        message=f"{validator_name} timed out after {self.timeout_seconds}s",
                    )
                ],
                "failed",
            )

        if completed.returncode == 0:
            return [], "passed"

        # Non-zero exit → capture both stdout and stderr as a single message.
        combined = (completed.stdout + "\n" + completed.stderr).strip()
        return (
            [
                TerraformValidationIssue(
                    severity="error",
                    source=validator_name,
                    message=f"{validator_name} failed: {combined[:2000]}",
                    remediation=(
                        "Inspect the rendered .tf files and fix the reported "
                        "syntax/resource errors."
                    ),
                )
            ],
            "failed",
        )

    # ── Stage 5: tfsec ────────────────────────────────────────────────────

    def _run_tfsec(
        self,
        workdir: Path,
    ) -> Tuple[List[TerraformSecurityIssue], ValidationStatus]:
        binary = shutil.which("tfsec")
        if not binary:
            return [], "skipped"

        try:
            completed = subprocess.run(
                [binary, str(workdir), "--format=json", "--no-color", "--soft-fail"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=self._isolated_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [], "failed"

        if not completed.stdout.strip():
            return [], "passed"

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [], "failed"

        findings = payload.get("results") or []
        issues: List[TerraformSecurityIssue] = []
        for f in findings:
            sev = _TFSEC_SEVERITY.get(str(f.get("severity", "")).upper(), "warning")
            issues.append(
                TerraformSecurityIssue(
                    severity=sev,
                    source="tfsec",
                    rule_id=str(f.get("rule_id") or f.get("long_id") or "unknown"),
                    file=(f.get("location") or {}).get("filename"),
                    line=(f.get("location") or {}).get("start_line"),
                    message=str(f.get("description") or "")[:500],
                    remediation=str(f.get("resolution") or "")[:500] or None,
                    resource=str(f.get("resource") or "") or None,
                )
            )
        status: ValidationStatus = "warnings" if issues else "passed"
        if any(i.severity in ("error", "critical") for i in issues):
            status = "failed"
        return issues, status

    # ── Stage 6: checkov ──────────────────────────────────────────────────

    def _run_checkov(
        self,
        workdir: Path,
    ) -> Tuple[List[TerraformSecurityIssue], ValidationStatus]:
        binary = shutil.which("checkov")
        if not binary:
            return [], "skipped"

        try:
            completed = subprocess.run(
                [binary, "-d", str(workdir), "-o", "json", "--quiet", "--soft-fail"],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=self._isolated_env(),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [], "failed"

        if not completed.stdout.strip():
            return [], "passed"

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [], "failed"

        results_block = payload if isinstance(payload, dict) else {}
        # checkov returns a top-level 'results' with 'failed_checks'/'passed_checks'.
        failed = (
            (results_block.get("results") or {}).get("failed_checks")
            or []
        )

        issues: List[TerraformSecurityIssue] = []
        for f in failed:
            sev = _CHECKOV_SEVERITY.get(str(f.get("severity", "")).upper(), "warning")
            issues.append(
                TerraformSecurityIssue(
                    severity=sev,
                    source="checkov",
                    rule_id=str(f.get("check_id") or "unknown"),
                    file=f.get("file_path"),
                    line=(f.get("file_line_range") or [None])[0],
                    message=str(f.get("check_name") or "")[:500],
                    remediation=str(f.get("guideline") or "")[:500] or None,
                    resource=str(f.get("resource") or "") or None,
                )
            )
        status: ValidationStatus = "warnings" if issues else "passed"
        if any(i.severity in ("error", "critical") for i in issues):
            status = "failed"
        return issues, status

    # ── Helpers ──────────────────────────────────────────────────────────

    def _materialize_artifacts(
        self,
        artifacts: Mapping[str, str],
        workdir: Path,
    ) -> None:
        """Write each artifact to a real file inside the temp working dir."""
        for key, content in artifacts.items():
            filename = _ARTIFACT_KEY_TO_FILENAME.get(key)
            if not filename:
                continue
            (workdir / filename).write_text(content, encoding="utf-8")

    def _isolated_env(self) -> Dict[str, str]:
        """Subprocess env: PATH + HOME only. Strip AWS_* and friends."""
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME") or os.environ.get("USERPROFILE", ""),
            "TF_IN_AUTOMATION": "true",
            "TF_INPUT": "0",
        }
        # Allow callers to opt-in additional vars (e.g. terraform plugin cache).
        for key in ("TF_PLUGIN_CACHE_DIR", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _finalize(
        self,
        issues: List[TerraformValidationIssue],
        security_issues: List[TerraformSecurityIssue],
        validators_run: Dict[ValidatorName, ValidationStatus],
        skipped: List[ValidatorName],
        start: float,
    ) -> TerraformValidationResult:
        # Aggregate status across all validators.
        has_error = any(i.severity in ("error", "critical") for i in issues) or any(
            s.severity in ("error", "critical") for s in security_issues
        )
        has_warning = any(i.severity == "warning" for i in issues) or any(
            s.severity == "warning" for s in security_issues
        )
        if has_error:
            status: ValidationStatus = "failed"
        elif has_warning:
            status = "warnings"
        elif validators_run and all(v == "skipped" for v in validators_run.values()):
            status = "skipped"
        else:
            status = "passed"

        duration_ms = int((time.perf_counter() - start) * 1000)
        return TerraformValidationResult(
            status=status,
            issues=issues,
            security_issues=security_issues,
            validators_run=validators_run,
            skipped_validators=skipped,
            duration_ms=duration_ms,
        )
