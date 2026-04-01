---
id: terraform_docker_local_stack
artifact_type: terraform
language: generic
framework: generic
project_type: backend_service
runtime: terraform
dependencies: []
tags: [terraform, docker, local]
description: Minimal Terraform pattern for a local Docker-based workload.
---
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

variable "build_context" {
  type = string
}

output "container_name" {
  value = "replace-with-generated-container-name"
}
