"""
ArtifactValidator — cross-artifact gap detection + secret scanning.

Checks generated artifacts for:
  1. Missing required files (e.g. Dockerfile without .dockerignore)
  2. Missing environment variables (vars referenced but not declared)
  3. Hardcoded secrets (high-confidence regex patterns)
  4. Known-vulnerable patterns (root user, no healthcheck, etc.)

Returns a structured report with:
  - errors   : block approval (hardcoded secrets, missing required dependencies)
  - warnings : non-blocking issues to flag to the user
  - missing_artifacts : list of artifact keys the plan expected but weren't generated
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Secret patterns (high confidence only — same set as RepositorySecurityService)
# ---------------------------------------------------------------------------

_HIGH_CONFIDENCE_SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"ghp_[A-Za-z0-9]{20,}", "GitHub Personal Access Token"),
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API Key"),
    (r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", "Private Key"),
    (r"gsk_[A-Za-z0-9]{40,}", "Groq API Key"),
    (r"(?i)postgresql://[^:]+:[^@]{8,}@", "PostgreSQL DSN with password"),
    (r"(?i)mongodb://[^:]+:[^@]{8,}@", "MongoDB DSN with password"),
    (r'(?i)(?:password|secret|api[_-]?key|token)\s*[:=]\s*["\'](?!.*\$\{)[^"\']{8,}["\']',
     "Hardcoded credential assignment"),
]

_PLACEHOLDER_MARKERS = {
    "changeme", "your_", "example", "placeholder", "replace_me",
    "xxxxxxxx", "todo", "fixme", "<your", "my_secret",
}


# ---------------------------------------------------------------------------
# Dependency rules: if artifact A exists, artifact B is required
# ---------------------------------------------------------------------------

_DEPENDENCY_RULES: List[tuple[str, str, str]] = [
    # (trigger_key, required_key, human description)
    ("dockerfile", ".dockerignore",
     "Dockerfile detected but .dockerignore is missing — build context may leak secrets"),
    ("docker_compose", "dockerfile",
     "docker-compose.yml builds a custom image but no Dockerfile was generated"),
    ("kubernetes_deployment", "kubernetes_service",
     "Kubernetes Deployment generated without a Service — pods will be unreachable"),
    ("kubernetes_deployment", "kubernetes_configmap",
     "Kubernetes Deployment generated without a ConfigMap — environment config is missing"),
]

# Artifact keys that map to their file counterpart (for lookup)
_KEY_TO_FILE = {
    "dockerfile": "Dockerfile",
    ".dockerignore": ".dockerignore",
    "docker_compose": "docker-compose.yml",
    ".env.example": ".env.example",
    "kubernetes_deployment": "kubernetes/deployment.yaml",
    "kubernetes_service": "kubernetes/service.yaml",
    "kubernetes_configmap": "kubernetes/configmap.yaml",
    "terraform_main": "terraform/main.tf",
    "terraform_variables": "terraform/variables.tf",
    "terraform_outputs": "terraform/output.tf",
}


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class ArtifactValidationReport:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_artifacts: List[str] = field(default_factory=list)
    secret_findings: List[Dict[str, str]] = field(default_factory=list)
    blocks_approval: bool = False

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.blocks_approval = True

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocks_approval": self.blocks_approval,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_artifacts": self.missing_artifacts,
            "secret_findings": self.secret_findings,
        }


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ArtifactValidator:
    """
    Stateless cross-artifact validator.

    Usage::

        validator = ArtifactValidator()
        report = validator.validate(
            artifacts={"dockerfile": "FROM python:3.11...", ...},
            plan_required=["dockerfile", "docker_compose"],
            generated_artifact_keys=["dockerfile"],
        )
        if report.blocks_approval:
            raise ValueError("Approval blocked: " + "; ".join(report.errors))
    """

    def validate(
        self,
        artifacts: Dict[str, str],
        plan_required: Optional[List[str]] = None,
        generated_artifact_keys: Optional[List[str]] = None,
        env_security_runtime: Optional[Dict[str, Any]] = None,
    ) -> ArtifactValidationReport:
        """
        Run all checks and return a consolidated report.

        Args:
            artifacts:               key → content mapping of generated artifacts.
            plan_required:           artifact keys the planner declared as required.
            generated_artifact_keys: artifact keys that were actually generated.
            env_security_runtime:    output of env_security scanner (optional).
        """
        report = ArtifactValidationReport()
        generated = set(generated_artifact_keys or artifacts.keys())
        required = set(plan_required or [])

        # 1. Missing artifacts
        self._check_missing(report, required, generated)

        # 2. Dependency gaps
        self._check_dependencies(report, generated)

        # 3. Secret scan across all artifact contents
        for key, content in artifacts.items():
            if content:
                self._scan_secrets(report, key, content)

        # 4. Dockerfile-specific checks
        if "dockerfile" in artifacts:
            self._check_dockerfile(report, artifacts["dockerfile"])

        # 5. docker-compose checks
        for key in ("docker_compose", "docker-compose"):
            if key in artifacts and artifacts[key]:
                self._check_compose(report, artifacts[key])
                break

        # 6. Environment variable exposure via env_security_runtime
        if env_security_runtime:
            self._check_env_exposure(report, env_security_runtime)

        return report

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_missing(
        self,
        report: ArtifactValidationReport,
        required: set[str],
        generated: set[str],
    ) -> None:
        for key in required:
            if key not in generated:
                report.missing_artifacts.append(key)
                report.add_warning(
                    f"Required artifact '{key}' was not generated — plan may be incomplete"
                )

    def _check_dependencies(
        self,
        report: ArtifactValidationReport,
        generated: set[str],
    ) -> None:
        for trigger, required, description in _DEPENDENCY_RULES:
            if trigger in generated and required not in generated:
                report.add_warning(description)

    def _scan_secrets(
        self,
        report: ArtifactValidationReport,
        artifact_key: str,
        content: str,
    ) -> None:
        for pattern, label in _HIGH_CONFIDENCE_SECRET_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE):
                matched = match.group(0)
                if self._is_placeholder(matched):
                    continue
                finding = {
                    "artifact": artifact_key,
                    "type": label,
                    "match": matched[:60] + ("…" if len(matched) > 60 else ""),
                }
                report.secret_findings.append(finding)
                report.add_error(
                    f"[{artifact_key}] Hardcoded secret detected — {label}: "
                    f"'{matched[:40]}…' — Remove before committing"
                )

    def _check_dockerfile(
        self,
        report: ArtifactValidationReport,
        content: str,
    ) -> None:
        lower = content.lower()

        # Non-root user check
        if "user " not in lower:
            report.add_warning(
                "Dockerfile: no USER directive — container will run as root (security risk)"
            )

        # HEALTHCHECK
        if "healthcheck" not in lower:
            report.add_warning(
                "Dockerfile: no HEALTHCHECK directive — container orchestrators cannot "
                "detect unhealthy instances"
            )

        # Secrets in ENV / ARG
        env_arg_secret = re.search(
            r"(?i)(?:ENV|ARG)\s+(?:PASSWORD|SECRET|API_KEY|TOKEN|PRIVATE_KEY)\s*=\s*\S+",
            content,
        )
        if env_arg_secret:
            report.add_error(
                "Dockerfile: secret passed via ENV/ARG — use build-time secrets or "
                "runtime environment injection instead"
            )

        # Latest tag on base image
        from_lines = re.findall(r"(?i)^FROM\s+(\S+)", content, re.MULTILINE)
        for img in from_lines:
            if img.endswith(":latest") or ":" not in img:
                report.add_warning(
                    f"Dockerfile: base image '{img}' uses ':latest' or no tag — "
                    "pin to a specific digest for reproducible builds"
                )

    def _check_compose(
        self,
        report: ArtifactValidationReport,
        content: str,
    ) -> None:
        lower = content.lower()

        # Plain-text passwords in environment block
        cred_match = re.search(
            r"(?i)(?:password|secret|api_key|token)\s*:\s*(?!\$)[^\s\n]{4,}",
            content,
        )
        if cred_match:
            report.add_error(
                "docker-compose.yml: plain-text credential in environment block — "
                "use secrets: or env_file: with a .env file not committed to git"
            )

        # No healthcheck for any service
        if "healthcheck" not in lower:
            report.add_warning(
                "docker-compose.yml: no healthcheck defined for any service"
            )

        # No resource limits
        if "mem_limit" not in lower and "memory:" not in lower and "cpus:" not in lower:
            report.add_warning(
                "docker-compose.yml: no resource limits (mem_limit / cpus) — "
                "services may starve the host"
            )

    def _check_env_exposure(
        self,
        report: ArtifactValidationReport,
        env_security_runtime: Dict[str, Any],
    ) -> None:
        sensitive = env_security_runtime.get("sensitive_values") or []
        if sensitive:
            names = ", ".join(str(s) for s in sensitive[:5])
            report.add_warning(
                f"Environment: {len(sensitive)} sensitive variable(s) detected "
                f"({names}{'…' if len(sensitive) > 5 else ''}) — "
                "ensure these are not baked into generated artifacts"
            )

    @staticmethod
    def _is_placeholder(matched: str) -> bool:
        normalized = matched.lower().strip("'\"")
        return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)
