"""The exact, whitelisted set of files the installation phase commits.

A generated DevOps setup is only runnable end-to-end when the repository carries,
alongside the two pipelines, the artifacts they consume: bootstrap.yml runs
``terraform init/apply`` against ``terraform/`` and both pipelines build from
``Dockerfile``. So installation commits EXACTLY four kinds of file:

    .github/workflows/bootstrap.yml   (Infrastructure pipeline)
    .github/workflows/deploy.yml      (Delivery pipeline)
    terraform/*.tf  +  terraform/*.tfvars   (provisioned by bootstrap)
    Dockerfile                        (built by both pipelines)

Everything else the platform generates (``.dockerignore``, ``docker-compose``,
``.env.*``, ``*.tfstate``, …) is deliberately NOT installed: the repository must
never receive an arbitrary file. This module is the single allow-list that
enforces that boundary; the git layer then writes + stages ONLY the paths it
returns (never ``git add -A``), so the security model is preserved.
"""

from __future__ import annotations

from typing import Dict, Mapping

from backend.app.services.repository_installation.models import (
    BOOTSTRAP_PATH,
    DEPLOY_PATH,
)

# Where Terraform config lives in the installed repo — bootstrap.yml's
# ``working-directory`` — and the single Docker artifact we install.
TERRAFORM_DIR = "terraform"
DOCKERFILE_PATH = "Dockerfile"

# Canonical key of the one Docker artifact we install (from get_docker_artifacts).
# The companion artifacts (.dockerignore / compose / .env.example) are NOT
# installed — only the Dockerfile the pipelines build from.
DOCKERFILE_ARTIFACT_KEY = "dockerfile"

# Only real Terraform CONFIG is installable — never state (``.tfstate``) and
# never anything else that might have leaked into the terraform artifact set.
INSTALLABLE_TERRAFORM_EXTENSIONS = (".tf", ".tfvars")


def is_installable_terraform_file(filename: str) -> bool:
    """True for a bare ``*.tf`` / ``*.tfvars`` basename (never a path or state)."""
    name = (filename or "").strip()
    if not name or "/" in name or "\\" in name:  # basename only — never a path
        return False
    return name.lower().endswith(INSTALLABLE_TERRAFORM_EXTENSIONS)


def build_installation_files(
    *,
    bootstrap: str,
    deploy: str,
    terraform_files: Mapping[str, str],
    docker_files: Mapping[str, str],
) -> Dict[str, str]:
    """Return ``{repo_path: content}`` — the COMPLETE set installation will write.

    Nothing outside the four whitelisted kinds is ever included. Terraform files
    are placed under ``terraform/`` (basename only, ``.tf``/``.tfvars`` only); the
    Docker ``dockerfile`` artifact becomes ``Dockerfile``. Empty contents are
    skipped so the installation never commits a blank file.
    """
    files: Dict[str, str] = {}

    if isinstance(bootstrap, str) and bootstrap.strip():
        files[BOOTSTRAP_PATH] = bootstrap
    if isinstance(deploy, str) and deploy.strip():
        files[DEPLOY_PATH] = deploy

    for filename, content in (terraform_files or {}).items():
        if is_installable_terraform_file(filename) and isinstance(content, str) and content.strip():
            files[f"{TERRAFORM_DIR}/{filename}"] = content

    dockerfile = (docker_files or {}).get(DOCKERFILE_ARTIFACT_KEY)
    if isinstance(dockerfile, str) and dockerfile.strip():
        files[DOCKERFILE_PATH] = dockerfile

    return files
