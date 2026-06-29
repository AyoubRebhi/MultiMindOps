"""The installation file allow-list (build_installation_files).

Pins the exact, whitelisted set of files installation commits so a generated
DevOps setup is runnable: the two pipelines + terraform/*.tf(vars) + Dockerfile,
and NOTHING else (no .dockerignore / compose / .env / *.tfstate / stray paths).
Pure assembly — no DB, no git.
"""

from __future__ import annotations

from backend.app.services.repository_installation.installation_files import (
    DOCKERFILE_PATH,
    build_installation_files,
    is_installable_terraform_file,
)
from backend.app.services.repository_installation.models import (
    BOOTSTRAP_PATH,
    DEPLOY_PATH,
)

TF = {
    "main.tf": 'resource "aws_eks_cluster" "main" {}\n',
    "variables.tf": 'variable "x" {}\n',
    "providers.tf": "terraform {}\n",
    "outputs.tf": 'output "y" { value = 1 }\n',
    "backend.tf": "terraform { backend \"s3\" {} }\n",
    "terraform.tfvars": 'project_name = "app"\n',
}
DOCKER = {
    "dockerfile": "FROM python:3.12-slim\n",
    "dockerignore": "__pycache__\n",
    "docker_compose": "services: {}\n",
    "env_example": "KEY=value\n",
}


def _build(tf=TF, docker=DOCKER):
    return build_installation_files(
        bootstrap="name: bootstrap\n",
        deploy="name: deploy\n",
        terraform_files=tf,
        docker_files=docker,
    )


def test_installs_pipelines_terraform_and_dockerfile_only():
    files = _build()
    assert set(files) == {
        BOOTSTRAP_PATH,
        DEPLOY_PATH,
        "terraform/main.tf",
        "terraform/variables.tf",
        "terraform/providers.tf",
        "terraform/outputs.tf",
        "terraform/backend.tf",
        "terraform/terraform.tfvars",
        DOCKERFILE_PATH,
    }


def test_terraform_files_go_under_terraform_dir_with_content_preserved():
    files = _build()
    assert files["terraform/main.tf"] == TF["main.tf"]
    assert files["terraform/terraform.tfvars"] == TF["terraform.tfvars"]


def test_only_the_dockerfile_artifact_is_installed():
    files = _build()
    assert files[DOCKERFILE_PATH] == DOCKER["dockerfile"]
    # The companion Docker artifacts are NOT installed.
    assert all(
        v != DOCKER["dockerignore"] and v != DOCKER["docker_compose"]
        for v in files.values()
    )
    assert "Dockerfile" in files and ".dockerignore" not in files


def test_tfstate_and_non_terraform_files_are_excluded():
    tf = {**TF, "terraform.tfstate": "{}", "notes.txt": "hi", "main.tfbackup": "x"}
    files = _build(tf=tf)
    assert not any(p.endswith(".tfstate") for p in files)
    assert "terraform/notes.txt" not in files
    assert "terraform/main.tfbackup" not in files


def test_empty_contents_are_skipped():
    tf = {"main.tf": 'resource "x" "y" {}\n', "variables.tf": "   ", "outputs.tf": ""}
    files = _build(tf=tf, docker={"dockerfile": "FROM scratch\n"})
    assert "terraform/main.tf" in files
    assert "terraform/variables.tf" not in files
    assert "terraform/outputs.tf" not in files


def test_no_dockerfile_artifact_means_no_dockerfile_installed():
    files = _build(docker={"dockerignore": "x\n"})
    assert DOCKERFILE_PATH not in files


def test_path_like_terraform_names_are_rejected():
    # Defence in depth: a basename with a separator must never produce a path.
    assert is_installable_terraform_file("main.tf") is True
    assert is_installable_terraform_file("terraform.tfvars") is True
    assert is_installable_terraform_file("../evil.tf") is False
    assert is_installable_terraform_file("nested/main.tf") is False
    assert is_installable_terraform_file("main.tfstate") is False
    assert is_installable_terraform_file("") is False
