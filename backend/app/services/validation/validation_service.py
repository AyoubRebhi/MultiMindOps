"""
DevSecOps artifact validation service.

Validates Dockerfiles, docker-compose, Kubernetes manifests, Terraform HCL,
GitHub Actions workflows, and generic JSON structures using a two-tier approach:

1. **Rule-based** — fast, deterministic, zero-cost checks.
2. **LLM fallback** — optional semantic validation when an LLMService is injected.

Classes
-------
ValidationResult    — immutable result value object (valid, issues, warnings)
ValidationService   — stateless validator, instantiate once and reuse
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Rule tables ───────────────────────────────────────────────────────────────

_DOCKERFILE_FORBIDDEN: List[tuple[str, str]] = [
    (
        r"(?i)(PASSWORD|SECRET|API_KEY|TOKEN)\s*=\s*(?!\$)[^\s\\]+",
        "Hardcoded credential detected",
    ),
]

_K8S_REQUIRED_FIELDS = ["apiVersion", "kind", "metadata"]
_GHA_REQUIRED_FIELDS = ["on", "jobs"]
_COMPOSE_REQUIRED_KEYS = ["services"]

_GENERIC_MARKERS = [
    'cmd ["python", "app.py"]',
    "env_var=example",
    "your-image:latest",
    "lorem ipsum",
    "<your-",
    "changeme",
    "placeholder",
    "todo: fill",
]


# ── Result object ─────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    """
    Immutable result from a validation check.

    Attributes
    ----------
    valid    : True when no blocking issues were found.
    issues   : List of error strings (each one is a blocking problem).
    warnings : List of advisory strings (non-blocking, best-practice hints).
    """

    valid: bool
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"valid": self.valid, "issues": self.issues, "warnings": self.warnings}

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Combine two results — valid only if both are valid."""
        return ValidationResult(
            valid=self.valid and other.valid,
            issues=list(dict.fromkeys(self.issues + other.issues)),
            warnings=list(dict.fromkeys(self.warnings + other.warnings)),
        )


# ── Service ───────────────────────────────────────────────────────────────────


class ValidationService:
    """
    Stateless DevSecOps artifact validator.

    Instantiate once (optionally injecting an LLMService for semantic checks):

        svc = ValidationService()                      # rule-based only
        svc = ValidationService(llm_service=llm_svc)  # + LLM fallback

    Key methods
    -----------
    validate_dockerfile(content)
    validate_docker_compose(content)
    validate_kubernetes_manifest(content, name)
    validate_github_actions(content, name)
    validate_terraform(content, name)
    validate_json_structure(data, required_keys, name)
    validate_artifacts(artifacts_dict)         → Dict[str, ValidationResult]
    aggregate_validation(results)              → summary dict
    is_generic_content(content)                → bool
    validate_with_llm_fallback(key, content, rule_result)
    """

    def __init__(self, llm_service: Optional[Any] = None):
        self._llm = llm_service

    # ── JSON / schema ─────────────────────────────────────────────────────────

    def validate_json_structure(
        self,
        data: Any,
        required_keys: List[str],
        name: str = "output",
    ) -> ValidationResult:
        """Verify that *data* is a dict containing all *required_keys*."""
        if not isinstance(data, dict):
            return ValidationResult(
                False,
                [f"{name}: expected JSON object, got {type(data).__name__}"],
            )
        issues = [f"{name}: missing required key '{k}'" for k in required_keys if k not in data]
        warnings = [
            f"{name}: key '{k}' is null/empty"
            for k in required_keys
            if k in data and not data[k]
        ]
        return ValidationResult(not issues, issues, warnings)

    # ── Dockerfile ────────────────────────────────────────────────────────────

    def validate_dockerfile(self, content: str) -> ValidationResult:
        """
        Validate a Dockerfile against common security and correctness rules.

        Checks
        ------
        - Must start with a FROM instruction (after comments).
        - Must not contain hardcoded credentials.

        Warnings
        --------
        - Missing HEALTHCHECK.
        - Using ':latest' tag.
        - Running as root (no USER instruction).
        """
        issues: List[str] = []
        warnings: List[str] = []

        if not content or not content.strip():
            return ValidationResult(False, ["Dockerfile: empty content"])

        lines = content.strip().splitlines()
        first_real = next(
            (ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")),
            "",
        )
        if not re.match(r"(?i)^FROM\s+", first_real):
            issues.append("Dockerfile: first non-comment instruction must be FROM")

        for pattern, msg in _DOCKERFILE_FORBIDDEN:
            if re.search(pattern, content, re.MULTILINE):
                issues.append(f"Dockerfile: {msg}")

        if not re.search(r"(?i)^HEALTHCHECK\s", content, re.MULTILINE):
            warnings.append("Dockerfile: consider adding a HEALTHCHECK instruction")
        if re.search(r"(?i)\bFROM\s+\S+:latest\b", content):
            warnings.append("Dockerfile: ':latest' tag — pin to a specific version for reproducibility")
        if not re.search(r"(?i)^USER\s+", content, re.MULTILINE):
            warnings.append("Dockerfile: no USER instruction — consider running as non-root")

        return ValidationResult(not issues, issues, warnings)

    # ── docker-compose ────────────────────────────────────────────────────────

    def validate_docker_compose(self, content: str) -> ValidationResult:
        """Validate docker-compose YAML: parsability and required keys."""
        try:
            import yaml  # soft dependency
        except ImportError:
            return ValidationResult(True, [], ["PyYAML not installed — skipping docker-compose validation"])

        if not content or not content.strip():
            return ValidationResult(False, ["docker-compose.yml: empty content"])

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return ValidationResult(False, [f"docker-compose.yml: YAML parse error — {exc}"])

        if not isinstance(data, dict):
            return ValidationResult(False, ["docker-compose.yml: expected a YAML mapping at root"])

        issues = [
            f"docker-compose.yml: missing required key '{k}'"
            for k in _COMPOSE_REQUIRED_KEYS
            if k not in data
        ]
        warnings: List[str] = []
        services = (data or {}).get("services") or {}
        if not services:
            warnings.append("docker-compose.yml: no services defined under 'services'")

        return ValidationResult(not issues, issues, warnings)

    # ── Kubernetes ────────────────────────────────────────────────────────────

    def validate_kubernetes_manifest(
        self, content: str, name: str = "k8s-manifest"
    ) -> ValidationResult:
        """Validate one or more YAML documents as Kubernetes manifests."""
        try:
            import yaml
        except ImportError:
            return ValidationResult(True, [], ["PyYAML not installed — skipping k8s validation"])

        if not content or not content.strip():
            return ValidationResult(False, [f"{name}: empty content"])

        try:
            docs = list(yaml.safe_load_all(content))
        except yaml.YAMLError as exc:
            return ValidationResult(False, [f"{name}: YAML parse error — {exc}"])

        issues: List[str] = []
        for i, doc in enumerate(docs or []):
            if not isinstance(doc, dict):
                continue
            for f in _K8S_REQUIRED_FIELDS:
                if f not in doc:
                    issues.append(f"{name} doc[{i}]: missing required field '{f}'")

        return ValidationResult(not issues, issues)

    # ── GitHub Actions ────────────────────────────────────────────────────────

    def validate_github_actions(
        self, content: str, name: str = "workflow"
    ) -> ValidationResult:
        """Validate a GitHub Actions workflow YAML."""
        try:
            import yaml
        except ImportError:
            return ValidationResult(True, [], ["PyYAML not installed — skipping GHA validation"])

        if not content or not content.strip():
            return ValidationResult(False, [f"{name}: empty content"])

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return ValidationResult(False, [f"{name}: YAML parse error — {exc}"])

        if not isinstance(data, dict):
            return ValidationResult(False, [f"{name}: expected a YAML mapping at root"])

        issues = [
            f"{name}: missing required field '{f}'"
            for f in _GHA_REQUIRED_FIELDS
            if f not in data
        ]
        warnings: List[str] = []
        if not (data or {}).get("jobs"):
            warnings.append(f"{name}: no jobs defined")

        return ValidationResult(not issues, issues, warnings)

    # ── Terraform ─────────────────────────────────────────────────────────────

    def validate_terraform(self, content: str, name: str = "main.tf") -> ValidationResult:
        """
        Validate Terraform HCL: presence of top-level blocks and absence of
        hardcoded credentials.
        """
        if not content or not content.strip():
            return ValidationResult(False, [f"{name}: empty content"])

        issues: List[str] = []
        warnings: List[str] = []

        if not re.search(
            r"(?im)^(terraform|provider|resource|data|module)\s", content
        ):
            issues.append(f"{name}: no terraform/provider/resource/data/module block found")

        if re.search(r'(?i)(password|secret|access_key)\s*=\s*"[^"${{]', content):
            issues.append(f"{name}: possible hardcoded credentials detected")

        return ValidationResult(not issues, issues, warnings)

    # ── Generic content quality ───────────────────────────────────────────────

    def is_generic_content(self, content: str) -> bool:
        """
        Return True if the content looks like an unfilled generic template
        (placeholders, dummy values, lorem ipsum, etc.).
        """
        lowered = (content or "").lower()
        return any(marker in lowered for marker in _GENERIC_MARKERS)

    # ── Batch validation ──────────────────────────────────────────────────────

    def validate_artifacts(
        self, artifacts: Dict[str, str]
    ) -> Dict[str, ValidationResult]:
        """
        Validate a dict of artifacts keyed by artifact name (e.g. "dockerfile",
        "docker_compose", "kubernetes_deployment", "terraform_main").

        Returns a mapping of the same keys to their ValidationResult.
        Unrecognised keys are silently skipped.
        """
        results: Dict[str, ValidationResult] = {}
        for key, content in (artifacts or {}).items():
            if not content:
                continue
            if key == "dockerfile":
                results[key] = self.validate_dockerfile(content)
            elif key == "docker_compose":
                results[key] = self.validate_docker_compose(content)
            elif key.startswith("kubernetes_"):
                results[key] = self.validate_kubernetes_manifest(content, key)
            elif key.startswith("terraform_"):
                results[key] = self.validate_terraform(content, f"{key}.tf")
            elif ".github" in key or key.startswith("cicd_"):
                results[key] = self.validate_github_actions(content, key)
        return results

    def aggregate_validation(
        self, results: Dict[str, ValidationResult]
    ) -> Dict[str, Any]:
        """
        Summarise a set of per-artifact ValidationResults into a single status dict.

        Returns
        -------
        {
            "status":        "valid" | "partial" | "invalid",
            "valid_count":   int,
            "invalid_count": int,
            "issues":        [str, ...],   # prefixed with artifact key
            "warnings":      [str, ...],
            "per_artifact":  {key: result.to_dict(), ...}
        }
        """
        all_issues = [f"{k}: {i}" for k, r in results.items() for i in r.issues]
        all_warnings = [f"{k}: {w}" for k, r in results.items() for w in r.warnings]
        invalid_keys = [k for k, r in results.items() if not r.valid]

        if not results:
            status = "valid"
        elif len(invalid_keys) == len(results):
            status = "invalid"
        elif invalid_keys:
            status = "partial"
        else:
            status = "valid"

        return {
            "status": status,
            "valid_count": len(results) - len(invalid_keys),
            "invalid_count": len(invalid_keys),
            "issues": all_issues,
            "warnings": all_warnings,
            "per_artifact": {k: r.to_dict() for k, r in results.items()},
        }

    # ── LLM fallback ─────────────────────────────────────────────────────────

    def validate_with_llm_fallback(
        self,
        artifact_key: str,
        content: str,
        rule_result: ValidationResult,
    ) -> ValidationResult:
        """
        Enhance a rule-based result with an LLM semantic check.

        Only fires when:
        - An LLMService was injected at construction time.
        - The rule-based check already passed (no blocking issues).

        Falls back silently to *rule_result* on any LLM error.
        """
        if not self._llm or not rule_result.valid:
            return rule_result

        try:
            resp = self._llm.chat_json(
                system_prompt=(
                    "You are a DevSecOps security and correctness auditor. "
                    "Inspect the provided artifact and return ONLY a valid JSON object: "
                    '{"valid": bool, "issues": ["..."], "warnings": ["..."]}. '
                    "Only flag real security or correctness problems — not style preferences."
                ),
                user_prompt=f"Artifact type: {artifact_key}\n\nContent:\n{content[:2000]}",
                temperature=0.0,
                max_tokens=400,
            )
            llm_result = ValidationResult(
                valid=bool(resp.get("valid", True)),
                issues=list(resp.get("issues") or []),
                warnings=list(resp.get("warnings") or []),
            )
            return rule_result.merge(llm_result)
        except Exception as exc:
            logger.warning(
                "LLM validation fallback failed for '%s': %s", artifact_key, exc
            )
            return rule_result
