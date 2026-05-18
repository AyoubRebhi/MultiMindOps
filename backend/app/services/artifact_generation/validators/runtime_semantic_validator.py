"""
RuntimeSemanticValidator — execution-aware Dockerfile validation.

Goes beyond structural checks (presence of FROM, WORKDIR, CMD) to catch
failures that only manifest at build or runtime:

  • Distro mismatch       — Alpine commands on Debian images and vice-versa
  • Invalid exec form     — single-quoted JSON arrays that Docker rejects
  • HEALTHCHECK gaps      — curl/wget used without being installed
  • Deprecated images     — openjdk:17-jre-slim → eclipse-temurin:17-jre
  • Multi-stage ghosts    — COPY --from referencing undefined build stage
  • Package manager wrong — apt on Alpine or apk on Debian

Each issue is returned as a RuntimeIssue with a suggested fix so the
self-critique loop and corrector can apply automatic patches.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Base-image metadata registry ──────────────────────────────────────────────

@dataclass
class ImageMetadata:
    family: str                    # "debian" | "alpine" | "distroless" | "ubi"
    package_manager: str           # "apt" | "apk" | "dnf" | "none"
    user_cmd: str                  # correct useradd command
    group_cmd: str                 # correct groupadd command
    deprecated: bool = False
    replacement: Optional[str] = None
    has_curl: bool = False         # curl pre-installed in the image
    has_wget: bool = False
    has_sh: bool = True


# Covers the most commonly used base images in DevSecOps pipelines.
# Prefix-matched: "eclipse-temurin:17" matches "eclipse-temurin:17-jre-alpine".
_REGISTRY: Dict[str, ImageMetadata] = {
    # ── eclipse-temurin (Debian variants) ────────────────────────────────────
    "eclipse-temurin:8-jre":   ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:11-jre":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:17-jre":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:21-jre":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:8-jdk":   ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:11-jdk":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:17-jdk":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "eclipse-temurin:21-jdk":  ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    # ── eclipse-temurin (Alpine variants) ────────────────────────────────────
    "eclipse-temurin:8-jre-alpine":   ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:11-jre-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:17-jre-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:21-jre-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:8-jdk-alpine":   ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:11-jdk-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:17-jdk-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    "eclipse-temurin:21-jdk-alpine":  ImageMetadata("alpine", "apk", "adduser -S",  "addgroup -S"),
    # ── Python ───────────────────────────────────────────────────────────────
    "python:3.9-slim":  ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    "python:3.10-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    "python:3.11-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    "python:3.12-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    "python:3.9-alpine":  ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "python:3.10-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "python:3.11-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "python:3.12-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    # ── Node.js ──────────────────────────────────────────────────────────────
    "node:18-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "node:20-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "node:22-alpine": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "node:18-slim":   ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "node:20-slim":   ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    "node:22-slim":   ImageMetadata("debian", "apt", "useradd -r",  "groupadd -r"),
    # ── Alpine base ───────────────────────────────────────────────────────────
    "alpine:3.17": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "alpine:3.18": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "alpine:3.19": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    "alpine:3.20": ImageMetadata("alpine", "apk", "adduser -S", "addgroup -S"),
    # ── Debian base ───────────────────────────────────────────────────────────
    "debian:bookworm-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    "debian:bullseye-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r"),
    # ── Ubuntu ────────────────────────────────────────────────────────────────
    "ubuntu:22.04": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r", has_curl=False),
    "ubuntu:24.04": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r", has_curl=False),
    # ── Deprecated / unavailable images ──────────────────────────────────────
    "openjdk:8-jre-slim":  ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                          deprecated=True, replacement="eclipse-temurin:8-jre"),
    "openjdk:11-jre-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                          deprecated=True, replacement="eclipse-temurin:11-jre"),
    "openjdk:17-jre-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                          deprecated=True, replacement="eclipse-temurin:17-jre"),
    "openjdk:21-jre-slim": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                          deprecated=True, replacement="eclipse-temurin:21-jre"),
    "openjdk:8-jdk":  ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                     deprecated=True, replacement="eclipse-temurin:8-jdk"),
    "openjdk:11-jdk": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                     deprecated=True, replacement="eclipse-temurin:11-jdk"),
    "openjdk:17-jdk": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                     deprecated=True, replacement="eclipse-temurin:17-jdk"),
    "openjdk:17": ImageMetadata("debian", "apt", "useradd -r", "groupadd -r",
                                  deprecated=True, replacement="eclipse-temurin:17-jdk"),
}


class BaseImageMetadataRegistry:
    """Looks up distro/package-manager metadata for a base image name."""

    @staticmethod
    def lookup(image: str) -> Optional[ImageMetadata]:
        """
        Exact match first, then longest prefix match.
        Returns None if the image is completely unknown.
        """
        image = image.strip().lower()
        # Strip digest suffix (sha256:...)
        image = re.sub(r"@sha256:[a-f0-9]+$", "", image)

        if image in _REGISTRY:
            return _REGISTRY[image]

        # Longest prefix match (e.g. "eclipse-temurin:17-jre-bookworm" → "eclipse-temurin:17-jre")
        best: Optional[Tuple[str, ImageMetadata]] = None
        for key, meta in _REGISTRY.items():
            if image.startswith(key):
                if best is None or len(key) > len(best[0]):
                    best = (key, meta)

        return best[1] if best else None

    @staticmethod
    def infer_family(image: str) -> str:
        """Best-effort distro family inference for unknown images."""
        img = image.lower()
        if "alpine" in img:
            return "alpine"
        if any(x in img for x in ("slim", "bookworm", "bullseye", "buster", "ubuntu", "debian")):
            return "debian"
        if any(x in img for x in ("ubi", "rhel", "centos", "fedora")):
            return "ubi"
        if "distroless" in img:
            return "distroless"
        return "unknown"


# ── Issue model ───────────────────────────────────────────────────────────────

@dataclass
class RuntimeIssue:
    rule: str
    severity: str          # "error" | "warning" | "recommendation"
    message: str
    suggestion: str
    line_hint: Optional[str] = None   # The offending Dockerfile line


@dataclass
class RuntimeSemanticResult:
    valid: bool
    issues: List[RuntimeIssue] = field(default_factory=list)
    detected_family: Optional[str] = None
    deprecated_images: List[str] = field(default_factory=list)

    @property
    def errors(self) -> List[RuntimeIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[RuntimeIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "detected_family": self.detected_family,
            "deprecated_images": self.deprecated_images,
            "issues": [
                {
                    "rule": i.rule,
                    "severity": i.severity,
                    "message": i.message,
                    "suggestion": i.suggestion,
                    "line_hint": i.line_hint,
                }
                for i in self.issues
            ],
        }


# ── Validator ─────────────────────────────────────────────────────────────────

# Alpine-specific user/group commands (invalid on Debian)
_ALPINE_USER_RE = re.compile(r"\baddgroup\s+-S\b|\badduser\s+-S\b", re.IGNORECASE)
# Debian-specific user/group commands (invalid on Alpine, just adduser/addgroup without -S)
_DEBIAN_USER_RE = re.compile(r"\bgroupadd\b|\buseradd\b", re.IGNORECASE)
# Invalid exec form — single-quoted JSON arrays
_BAD_EXEC_FORM_RE = re.compile(
    r"(?m)^(CMD|ENTRYPOINT|RUN)\s+\[.*?'.*?'.*?\]",
)
# Shell-form RUN with Python list syntax (common LLM mistake)
_PYTHON_LIST_RUN_RE = re.compile(
    r"(?m)^RUN\s+\[.*?\]"
)
# apt-get patterns used on Alpine
_APT_ON_ALPINE_RE = re.compile(r"\bapt-get\b|\bapt\b", re.IGNORECASE)
# apk patterns used on Debian
_APK_ON_DEBIAN_RE = re.compile(r"\bapk\s+add\b|\bapk\s+update\b", re.IGNORECASE)
# HEALTHCHECK using curl or wget
_HC_CURL_RE = re.compile(r"(?m)^HEALTHCHECK.*curl", re.IGNORECASE)
_HC_WGET_RE = re.compile(r"(?m)^HEALTHCHECK.*wget", re.IGNORECASE)
# Installation of curl/wget anywhere in the Dockerfile
_INSTALL_CURL_RE = re.compile(r"\bcurl\b", re.IGNORECASE)
_INSTALL_WGET_RE = re.compile(r"\bwget\b", re.IGNORECASE)
# FROM lines
_FROM_RE = re.compile(r"(?im)^FROM\s+(\S+?)(?:\s+AS\s+\S+)?$")
# COPY --from=<stage>
_COPY_FROM_RE = re.compile(r"(?im)^COPY\s+--from=(\S+)", re.IGNORECASE)
# Unresolved Jinja / template placeholders. Order matters: ${{ before {{ so the
# GitHub Actions form is recognised distinctly. ERB tags are matched too.
_UNRESOLVED_TEMPLATE_RES: list[tuple[str, "re.Pattern[str]"]] = [
    ("github_actions_expression", re.compile(r"\$\{\{\s*([^{}\n]+?)\s*\}\}")),
    ("erb_expression",            re.compile(r"<%=\s*([^<>\n]+?)\s*%>")),
    ("erb_control",               re.compile(r"<%\s*([^<>\n]+?)\s*%>")),
    ("jinja_control",             re.compile(r"\{%\s*([^{}\n]+?)\s*%\}")),
    ("jinja_expression",          re.compile(r"\{\{\s*([^{}\n]+?)\s*\}\}")),
]


class RuntimeSemanticValidator:
    """
    Validates a Dockerfile for runtime and execution-time correctness.

    Unlike DockerfileValidator (structural), this validator catches issues
    that only appear when the image is built or run — distro mismatches,
    invalid exec-form syntax, missing health-check dependencies, etc.

    Now also accepts optional compose_topology and build_context_report for
    topology-aware cross-artifact validation.
    """

    def __init__(self) -> None:
        self._registry = BaseImageMetadataRegistry()

    def validate(
        self,
        content: str,
        compose_topology: Optional[Dict[str, Any]] = None,
        build_context_report: Optional[Dict[str, Any]] = None,
    ) -> RuntimeSemanticResult:
        if not content or not content.strip():
            return RuntimeSemanticResult(valid=True)

        issues: List[RuntimeIssue] = []
        deprecated_images: List[str] = []

        # ── Rule: unresolved template variables (highest priority) ────────────
        # Any {{ var }} / {% ... %} / ${{ ... }} / <% ... %> token reaching this
        # point means artifact rendering was incomplete. Treat as a hard error
        # so the pre-build gate refuses to start a build.
        self._check_unresolved_templates(content, issues)

        # ── Parse FROM statements and build stage registry ────────────────────
        from_images = _FROM_RE.findall(content)
        stage_names: List[str] = []
        for m in re.finditer(r"(?im)^FROM\s+(\S+?)(?:\s+AS\s+(\S+))?$", content):
            if m.group(2):
                stage_names.append(m.group(2).lower())

        # ── Determine runtime image (last FROM = final stage) ─────────────────
        runtime_image = from_images[-1] if from_images else None
        meta = self._registry.lookup(runtime_image) if runtime_image else None
        family = (
            meta.family
            if meta
            else self._registry.infer_family(runtime_image or "")
        )

        logger.debug(
            "[RuntimeSemanticValidator] runtime_image=%s family=%s",
            runtime_image, family,
        )

        # ── Rule: deprecated base images ──────────────────────────────────────
        for img in from_images:
            img_meta = self._registry.lookup(img)
            if img_meta and img_meta.deprecated:
                deprecated_images.append(img)
                replacement = img_meta.replacement or "a current equivalent"
                issues.append(RuntimeIssue(
                    rule="deprecated_base_image",
                    severity="error",
                    message=f"Base image '{img}' is deprecated or unavailable on Docker Hub.",
                    suggestion=f"Replace with: FROM {replacement}",
                    line_hint=f"FROM {img}",
                ))

        # ── Rule: invalid exec form (single-quoted JSON arrays) ───────────────
        for match in _BAD_EXEC_FORM_RE.finditer(content):
            line = match.group(0).strip()
            fixed = line.replace("'", '"')
            issues.append(RuntimeIssue(
                rule="invalid_exec_form_quotes",
                severity="error",
                message=(
                    f"Invalid JSON exec form — single quotes are not valid JSON. "
                    f"Docker will reject this instruction."
                ),
                suggestion=f"Use double quotes: {fixed}",
                line_hint=line,
            ))

        # ── Rule: shell-form RUN with list syntax (Python list mistake) ───────
        for match in _PYTHON_LIST_RUN_RE.finditer(content):
            line = match.group(0).strip()
            if "'" in line or '"' in line:
                issues.append(RuntimeIssue(
                    rule="run_with_list_syntax",
                    severity="error",
                    message=(
                        "RUN does not support JSON exec form — it always uses shell form. "
                        "Remove the brackets and quotes."
                    ),
                    suggestion=f"Change to: RUN mvn clean package -DskipTests",
                    line_hint=line,
                ))

        # ── Distro-specific checks (only if we know the runtime family) ───────
        if family in ("debian", "alpine"):
            self._check_distro_commands(content, family, issues)
            self._check_package_manager(content, family, issues)

        # ── Rule: HEALTHCHECK uses curl/wget without installation ─────────────
        self._check_healthcheck_deps(content, issues)

        # ── Rule: COPY --from references undefined build stage ────────────────
        self._check_copy_from_stages(content, stage_names, issues)

        # ── Topology-aware checks (compose + build-context) ───────────────────
        if compose_topology:
            self._check_compose_port_consistency(content, compose_topology, issues)
            self._check_compose_command_duplication(content, compose_topology, issues)
            self._check_runtime_mode_mismatch(content, compose_topology, issues)
            self._check_volume_conflicts(content, compose_topology, issues)

        if build_context_report:
            self._check_build_context_issues(build_context_report, issues)

        has_errors = any(i.severity == "error" for i in issues)

        logger.info(
            "[RuntimeSemanticValidator] family=%s errors=%d warnings=%d deprecated=%d",
            family,
            sum(1 for i in issues if i.severity == "error"),
            sum(1 for i in issues if i.severity == "warning"),
            len(deprecated_images),
        )

        return RuntimeSemanticResult(
            valid=not has_errors,
            issues=issues,
            detected_family=family,
            deprecated_images=deprecated_images,
        )

    # ── Private rule implementations ──────────────────────────────────────────

    def _check_unresolved_templates(
        self,
        content: str,
        issues: List[RuntimeIssue],
    ) -> None:
        """Reject any artifact still containing template placeholders."""
        seen: set = set()
        for line_no, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.rstrip()
            for pattern_name, regex in _UNRESOLVED_TEMPLATE_RES:
                for m in regex.finditer(line):
                    token = m.group(0)
                    variable = m.group(1).strip()
                    key = (token, line_no)
                    if key in seen:
                        continue
                    seen.add(key)
                    issues.append(RuntimeIssue(
                        rule="unresolved_template_variable",
                        severity="error",
                        message=(
                            f"Unresolved template variable '{token}' detected in "
                            f"Dockerfile (line {line_no}). Artifact rendering "
                            "failed before execution."
                        ),
                        suggestion=(
                            f"Variable '{variable}' was not substituted by the "
                            f"section generator (pattern={pattern_name}). Rerun "
                            "the Docker phase or edit the Dockerfile to remove "
                            "the placeholder."
                        ),
                        line_hint=line,
                    ))

    def _check_distro_commands(
        self,
        content: str,
        family: str,
        issues: List[RuntimeIssue],
    ) -> None:
        if family == "debian":
            for match in _ALPINE_USER_RE.finditer(content):
                cmd = match.group(0)
                issues.append(RuntimeIssue(
                    rule="alpine_cmd_on_debian",
                    severity="error",
                    message=(
                        f"Alpine user command '{cmd}' used on Debian-based image. "
                        "This command does not exist on Debian/Ubuntu systems."
                    ),
                    suggestion=(
                        "Replace with Debian equivalents:\n"
                        "  RUN groupadd -r appgroup && useradd -r -g appgroup appuser"
                    ),
                    line_hint=cmd,
                ))

        elif family == "alpine":
            for match in _DEBIAN_USER_RE.finditer(content):
                cmd = match.group(0)
                issues.append(RuntimeIssue(
                    rule="debian_cmd_on_alpine",
                    severity="error",
                    message=(
                        f"Debian user command '{cmd}' used on Alpine-based image. "
                        "Alpine uses 'addgroup'/'adduser' instead."
                    ),
                    suggestion=(
                        "Replace with Alpine equivalents:\n"
                        "  RUN addgroup -S appgroup && adduser -S appuser -G appgroup"
                    ),
                    line_hint=cmd,
                ))

    def _check_package_manager(
        self,
        content: str,
        family: str,
        issues: List[RuntimeIssue],
    ) -> None:
        if family == "alpine" and _APT_ON_ALPINE_RE.search(content):
            issues.append(RuntimeIssue(
                rule="apt_on_alpine",
                severity="error",
                message="apt-get used on Alpine image — Alpine uses 'apk', not 'apt-get'.",
                suggestion="Replace 'apt-get install' with 'apk add --no-cache'",
            ))

        if family == "debian" and _APK_ON_DEBIAN_RE.search(content):
            issues.append(RuntimeIssue(
                rule="apk_on_debian",
                severity="error",
                message="apk used on Debian/Ubuntu image — Debian uses 'apt-get', not 'apk'.",
                suggestion="Replace 'apk add' with 'apt-get update && apt-get install -y --no-install-recommends'",
            ))

    def _check_healthcheck_deps(
        self,
        content: str,
        issues: List[RuntimeIssue],
    ) -> None:
        uses_curl_hc = bool(_HC_CURL_RE.search(content))
        uses_wget_hc = bool(_HC_WGET_RE.search(content))

        if uses_curl_hc:
            # Check whether curl is installed anywhere in the Dockerfile
            # (excluding the HEALTHCHECK line itself)
            non_hc_content = re.sub(r"(?m)^HEALTHCHECK.*$", "", content)
            if not _INSTALL_CURL_RE.search(non_hc_content):
                issues.append(RuntimeIssue(
                    rule="healthcheck_missing_curl",
                    severity="error",
                    message=(
                        "HEALTHCHECK uses 'curl' but curl is not installed in the image. "
                        "The health check will fail at runtime."
                    ),
                    suggestion=(
                        "Add curl installation before the HEALTHCHECK:\n"
                        "  # Debian: RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*\n"
                        "  # Alpine: RUN apk add --no-cache curl"
                    ),
                ))

        if uses_wget_hc:
            non_hc_content = re.sub(r"(?m)^HEALTHCHECK.*$", "", content)
            if not _INSTALL_WGET_RE.search(non_hc_content):
                issues.append(RuntimeIssue(
                    rule="healthcheck_missing_wget",
                    severity="error",
                    message=(
                        "HEALTHCHECK uses 'wget' but wget is not installed in the image. "
                        "The health check will fail at runtime."
                    ),
                    suggestion=(
                        "Add wget installation before the HEALTHCHECK:\n"
                        "  # Debian: RUN apt-get update && apt-get install -y --no-install-recommends wget && rm -rf /var/lib/apt/lists/*\n"
                        "  # Alpine: RUN apk add --no-cache wget"
                    ),
                ))

    def _check_copy_from_stages(
        self,
        content: str,
        stage_names: List[str],
        issues: List[RuntimeIssue],
    ) -> None:
        for match in _COPY_FROM_RE.finditer(content):
            ref = match.group(1).lower()
            # Skip numeric stage references (COPY --from=0)
            if ref.isdigit():
                continue
            if ref not in stage_names:
                issues.append(RuntimeIssue(
                    rule="undefined_build_stage",
                    severity="error",
                    message=(
                        f"COPY --from={ref} references stage '{ref}' which is not "
                        "defined by any AS clause in this Dockerfile."
                    ),
                    suggestion=(
                        f"Ensure an earlier FROM instruction includes 'AS {ref}', e.g.:\n"
                        f"  FROM eclipse-temurin:17-jdk AS {ref}"
                    ),
                    line_hint=match.group(0).strip(),
                ))

    # ── Topology-aware rule implementations ───────────────────────────────────

    def _check_compose_port_consistency(
        self,
        content: str,
        compose_topology: Dict[str, Any],
        issues: List[RuntimeIssue],
    ) -> None:
        """Warn when EXPOSE port does not match the container port in compose."""
        expose_ports: List[int] = []
        for m in re.finditer(r"(?im)^EXPOSE\s+(\d+)", content):
            try:
                expose_ports.append(int(m.group(1)))
            except ValueError:
                pass

        if not expose_ports:
            return

        compose_container_ports: List[int] = []
        backend = compose_topology.get("backend_service")
        for svc in compose_topology.get("services", []):
            if svc.get("name") != backend:
                continue
            for port_mapping in svc.get("ports") or []:
                try:
                    container_port = int(str(port_mapping).split(":")[-1].split("/")[0])
                    compose_container_ports.append(container_port)
                except (ValueError, IndexError):
                    pass

        if not compose_container_ports:
            return

        for ep in expose_ports:
            if compose_container_ports and ep not in compose_container_ports:
                issues.append(RuntimeIssue(
                    rule="compose_port_mismatch",
                    severity="warning",
                    message=(
                        f"Dockerfile EXPOSEs port {ep} but docker-compose maps "
                        f"container port(s) {compose_container_ports}. "
                        "Ensure the application listens on the compose-defined port."
                    ),
                    suggestion=(
                        f"Either change EXPOSE to match compose (e.g. EXPOSE {compose_container_ports[0]}) "
                        "or update the compose port mapping."
                    ),
                ))

    def _check_compose_command_duplication(
        self,
        content: str,
        compose_topology: Dict[str, Any],
        issues: List[RuntimeIssue],
    ) -> None:
        """Warn when compose overrides CMD/ENTRYPOINT, making the Dockerfile's redundant."""
        backend = compose_topology.get("backend_service")
        compose_cmd: Optional[str] = None
        for svc in compose_topology.get("services", []):
            if svc.get("name") == backend:
                compose_cmd = svc.get("command") or svc.get("entrypoint")
                break

        if not compose_cmd:
            return

        has_dockerfile_cmd = bool(re.search(r"(?im)^CMD\b", content))
        has_dockerfile_ep = bool(re.search(r"(?im)^ENTRYPOINT\b", content))

        if has_dockerfile_cmd or has_dockerfile_ep:
            issues.append(RuntimeIssue(
                rule="compose_command_override",
                severity="warning",
                message=(
                    f"docker-compose defines 'command: {compose_cmd[:80]}' which overrides "
                    "the Dockerfile CMD/ENTRYPOINT at runtime. "
                    "Ensure both define the same startup semantics."
                ),
                suggestion=(
                    "In production (no compose), the Dockerfile CMD/ENTRYPOINT is used. "
                    "In development (with compose), the compose command takes precedence. "
                    "Make sure both are consistent."
                ),
            ))

    def _check_runtime_mode_mismatch(
        self,
        content: str,
        compose_topology: Dict[str, Any],
        issues: List[RuntimeIssue],
    ) -> None:
        """Warn when compose declares development mode but the Dockerfile has no hot-reload."""
        runtime_mode = compose_topology.get("runtime_mode", "production")
        hot_reload = compose_topology.get("hot_reload", False)

        if runtime_mode != "development" and not hot_reload:
            return

        # In development mode: warn if Dockerfile has workers (gunicorn -w N, --workers N)
        prod_worker_re = re.compile(
            r"(?:gunicorn|uvicorn).*(?:-w\s+[2-9]|--workers\s+[2-9])", re.IGNORECASE
        )
        if prod_worker_re.search(content):
            issues.append(RuntimeIssue(
                rule="runtime_mode_mismatch",
                severity="warning",
                message=(
                    "docker-compose is configured for development mode (hot-reload) "
                    "but the Dockerfile CMD uses multiple workers — a production pattern. "
                    "Consider using a single worker with --reload in development."
                ),
                suggestion=(
                    "For development: use 'uvicorn app:app --reload --workers 1'\n"
                    "For production: use 'gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker'"
                ),
            ))

    def _check_volume_conflicts(
        self,
        content: str,
        compose_topology: Dict[str, Any],
        issues: List[RuntimeIssue],
    ) -> None:
        """Warn when compose mounts override paths that the Dockerfile writes to."""
        backend = compose_topology.get("backend_service")
        mounted_paths: List[str] = []
        for svc in compose_topology.get("services", []):
            if svc.get("name") != backend:
                continue
            for vol in svc.get("volumes") or []:
                vol_str = str(vol)
                # Named volume (no colon or just name:) — skip
                if ":" not in vol_str:
                    continue
                parts = vol_str.split(":")
                if len(parts) >= 2:
                    mounted_paths.append(parts[1].split(":")[0])

        if not mounted_paths:
            return

        workdir_match = re.search(r"(?im)^WORKDIR\s+(\S+)", content)
        workdir = workdir_match.group(1) if workdir_match else None

        if workdir and any(mp == workdir or mp.startswith(workdir + "/") for mp in mounted_paths):
            issues.append(RuntimeIssue(
                rule="volume_workdir_conflict",
                severity="warning",
                message=(
                    f"docker-compose mounts a volume over the Dockerfile WORKDIR '{workdir}'. "
                    "The container's WORKDIR contents will be hidden by the host mount in dev mode."
                ),
                suggestion=(
                    "This is normal for development hot-reload setups — the host source code "
                    "overlays the container image content. Ensure the production image does not "
                    "depend on compose volume mounts."
                ),
            ))

    def _check_build_context_issues(
        self,
        build_context_report: Dict[str, Any],
        issues: List[RuntimeIssue],
    ) -> None:
        """Surface build-context COPY resolution failures as runtime issues."""
        for issue_msg in build_context_report.get("issues") or []:
            issues.append(RuntimeIssue(
                rule="copy_source_missing",
                severity="error",
                message=issue_msg,
                suggestion=(
                    "Verify the COPY source path is relative to the Docker build context. "
                    "Check that the file exists and is not in .dockerignore."
                ),
            ))
        for warn_msg in build_context_report.get("warnings") or []:
            issues.append(RuntimeIssue(
                rule="copy_dependency_warning",
                severity="warning",
                message=warn_msg,
                suggestion=(
                    "Ensure the dependency file is committed to the repository and "
                    "not excluded by .dockerignore."
                ),
            ))
