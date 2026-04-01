---
id: security_compose_notes
artifact_type: security
language: generic
framework: generic
project_type: generic
runtime: docker_compose
dependencies: []
tags: [security, docker-compose]
description: Security reminders for Docker Compose generation.
---
- Reference secrets via environment variables, not hardcoded values.
- Limit published ports to required services.
- Add persistent volumes only where they are needed.
