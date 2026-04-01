---
id: security_docker_notes
artifact_type: security
language: generic
framework: generic
project_type: generic
runtime: docker
dependencies: []
tags: [security, docker]
description: Security reminders for Docker artifact generation.
---
- Prefer minimal base images.
- Avoid embedding secrets in image layers.
- Expose only required ports.
- Use non-root users when practical.
